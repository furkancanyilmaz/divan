'use strict';

/*
 * Development-only real-browser acceptance matrix for Divan's embedded
 * Android shell. Run against a disposable local server/DB; this never writes
 * application files or production data.
 */
const { chromium } = require('playwright');

const BASE_URL = process.env.DIVAN_ACCEPTANCE_URL || 'http://127.0.0.1:8879';
const VIEWPORTS = [
  [320, 568], [568, 320], [360, 800], [800, 360],
  [412, 915], [915, 412], [480, 960], [960, 480],
];
const THEMES = {
  white: 'rgb(255, 255, 255)',
  paper: 'rgb(247, 241, 230)',
  dark: 'rgb(25, 29, 32)',
};
const SCALES = [1, 2];
const failures = [];
const stats = {
  cases: 0,
  homeSurfaces: 0,
  targets: 0,
  iconGeometry: 0,
  chatTimestamps: 0,
  settingsScrollers: 0,
};

function check(condition, label, detail = '') {
  if (!condition) failures.push(detail ? `${label}: ${detail}` : label);
}

function near(a, b, tolerance = 1.25) {
  return Math.abs(Number(a) - Number(b)) <= tolerance;
}

async function visibleRects(page, selectors) {
  return page.evaluate((items) => items.flatMap((selector) =>
    [...document.querySelectorAll(selector)].filter((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return !element.hidden && style.display !== 'none' &&
        style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    }).map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        selector,
        id: element.id || element.getAttribute('aria-label') || element.textContent.trim().slice(0, 32),
        x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom,
        width: rect.width, height: rect.height,
      };
    })), selectors);
}

async function checkTargets(page, selectors, label, minimum = 44) {
  const rects = await visibleRects(page, selectors);
  for (const rect of rects) {
    stats.targets += 1;
    check(rect.width + 0.1 >= minimum && rect.height + 0.1 >= minimum,
      `${label} target ${rect.id}`,
      `${rect.width.toFixed(1)}×${rect.height.toFixed(1)} < ${minimum}`);
  }
  return rects;
}

async function assertNoPageOverflow(page, label) {
  const dimensions = await page.evaluate(() => ({
    viewport: innerWidth,
    htmlScroll: document.documentElement.scrollWidth,
    bodyScroll: document.body.scrollWidth,
    rootX: document.documentElement.scrollLeft,
    bodyX: document.body.scrollLeft,
  }));
  check(dimensions.htmlScroll <= dimensions.viewport + 1,
    `${label} document overflow`, JSON.stringify(dimensions));
  check(dimensions.bodyScroll <= dimensions.viewport + 1,
    `${label} body overflow`, JSON.stringify(dimensions));
  check(dimensions.rootX === 0 && dimensions.bodyX === 0,
    `${label} starts horizontally scrolled`, JSON.stringify(dimensions));
}

async function assertWithinViewport(page, selectors, label) {
  const viewportWidth = page.viewportSize().width;
  const rects = await visibleRects(page, selectors);
  for (const rect of rects) {
    check(rect.x >= -1.25 && rect.right <= viewportWidth + 1.25,
      `${label} bounds ${rect.id}`,
      `x=${rect.x.toFixed(1)} right=${rect.right.toFixed(1)} viewport=${viewportWidth}`);
  }
}

async function checkHome(page, expectedColor, label) {
  await page.waitForSelector('#mobileHome:not([hidden])');
  await assertNoPageOverflow(page, `${label} home`);
  await assertWithinViewport(page, [
    '#mobileHome', '.mobileHomeHeader', '#mobileHomeSearchBar',
    '#mobileConversationList', '#mobileHomeBottomNav',
    '#mobileNewConversationFab',
  ], `${label} home`);

  const surfaces = await page.evaluate(() => {
    const ids = [
      '#mobileHome', '.mobileHomeHeader', '#mobileConversationList',
      '#mobileHomeBottomNav',
    ];
    return Object.fromEntries(ids.map((selector) => [selector,
      getComputedStyle(document.querySelector(selector)).backgroundColor]));
  });
  for (const [selector, color] of Object.entries(surfaces)) {
    stats.homeSurfaces += 1;
    check(color === expectedColor, `${label} ${selector} surface`,
      `${color} !== ${expectedColor}`);
  }
  const pinned = await page.locator('.mobileConversationItem.isPinned').first()
    .evaluate((element) => getComputedStyle(element).backgroundColor);
  check(pinned === 'rgba(0, 0, 0, 0)' || pinned === expectedColor,
    `${label} pinned row tint`, pinned);

  await checkTargets(page, [
    '#mobileHomeSearchBar', '#mobileHomeChatsTab', '#mobileHomePeopleTab',
    '#mobileHomeMore', '#mobileNewConversationFab',
  ], `${label} home`);

  const icons = await page.evaluate(() => [
    '#mobileHomeChatsTab', '#mobileHomePeopleTab', '#mobileHomeMore',
    '#mobileNewConversationFab',
  ].map((selector) => {
    const button = document.querySelector(selector);
    const icon = button && button.querySelector('svg');
    if (!button || !icon) return { selector, missing: true };
    const b = button.getBoundingClientRect();
    const i = icon.getBoundingClientRect();
    return {
      selector, width: i.width, height: i.height,
      centerDeltaX: Math.abs((i.left + i.width / 2) - (b.left + b.width / 2)),
      rawGlyph: /^[+⋮←→⚙]+$/u.test(button.textContent.trim()),
    };
  }));
  for (const icon of icons) {
    stats.iconGeometry += 1;
    check(!icon.missing, `${label} ${icon.selector} icon missing`);
    if (!icon.missing) {
      check(icon.width >= 18 && icon.width <= 32 &&
          icon.height >= 18 && icon.height <= 32,
        `${label} ${icon.selector} icon size`,
        `${icon.width.toFixed(1)}×${icon.height.toFixed(1)}`);
      check(icon.centerDeltaX <= 4.5,
        `${label} ${icon.selector} icon centering`,
        `horizontal delta ${icon.centerDeltaX.toFixed(1)}`);
      check(!icon.rawGlyph, `${label} ${icon.selector} raw Unicode control`);
    }
  }
}

async function checkSettings(page, label) {
  await page.evaluate(() => showSettings());
  await page.waitForSelector('#settingsOverlay.show');
  await assertNoPageOverflow(page, `${label} settings`);
  await assertWithinViewport(page, [
    '#settingsOverlay', '#settingsOverlay .settingsModal',
    '.mobileSettingsHeader', '.mobileSettingsNav',
    '.mobileSettingsToolGrid', '.settingsSaveBar',
  ], `${label} settings`);
  await checkTargets(page, [
    '#mobileSettingsBack', '.mobileSettingsNav button',
    '.mobileSettingsToolGrid button', '.settingsSaveBar button',
  ], `${label} settings`);

  const nav = await page.locator('.mobileSettingsNav').evaluate((element) => {
    const before = element.scrollLeft;
    element.scrollLeft = element.scrollWidth;
    const after = element.scrollLeft;
    return {
      before, after, scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
      overflowX: getComputedStyle(element).overflowX,
    };
  });
  stats.settingsScrollers += 1;
  if (nav.scrollWidth > nav.clientWidth + 1) {
    check(nav.after > nav.before, `${label} settings nav unreachable`,
      JSON.stringify(nav));
    check(['auto', 'scroll'].includes(nav.overflowX),
      `${label} settings nav overflow contract`, JSON.stringify(nav));
  }

  const modal = page.locator('#settingsOverlay .settingsModal');
  await modal.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  const save = await page.locator('#settingsSave').boundingBox();
  check(save && save.height >= 48 && save.x >= -1 &&
      save.x + save.width <= page.viewportSize().width + 1,
    `${label} settings save bar`, JSON.stringify(save));

  await page.click('#mobileSettingsBack');
  await page.waitForSelector('#settingsOverlay', { state: 'hidden' });
}

async function checkChat(page, label) {
  await page.click('[data-conversation-id="2"]');
  await page.waitForSelector('#conversationScreen:not([hidden])');
  await page.waitForSelector('#chat .row.therapist');
  await assertNoPageOverflow(page, `${label} chat`);
  await assertWithinViewport(page, [
    '#conversationScreen', '#mobileHeader', '#chat', '#inputBar',
    '#inputInner', '#composerPlusBtn', '#msg', '#send',
  ], `${label} chat`);
  await checkTargets(page, [
    '#mobileBackBtn', '#mobilePersonaIdentity', '#mobileHeaderMore',
    '#composerPlusBtn', '#msg', '#send',
  ], `${label} chat`);

  const composer = await page.evaluate(() => {
    const plus = document.querySelector('#composerPlusBtn').getBoundingClientRect();
    const send = document.querySelector('#send').getBoundingClientRect();
    const input = document.querySelector('#msg').getBoundingClientRect();
    return {
      plusY: plus.y, plusH: plus.height, plusCenter: plus.y + plus.height / 2,
      sendY: send.y, sendH: send.height, sendCenter: send.y + send.height / 2,
      plusBottom: plus.bottom, sendBottom: send.bottom,
      inputBottom: input.bottom,
    };
  });
  check(near(composer.plusCenter, composer.sendCenter, 1.5),
    `${label} composer button baseline`, JSON.stringify(composer));
  check(near(composer.plusBottom, composer.inputBottom, 1.5) &&
      near(composer.sendBottom, composer.inputBottom, 1.5),
    `${label} composer bottom alignment`, JSON.stringify(composer));

  const timestamps = await page.evaluate(() =>
    [...document.querySelectorAll('#chat .bubble')].map((bubble) => {
      const content = bubble.querySelector('.bubbleContent');
      const time = bubble.querySelector('.messageTime');
      if (!content || !time) return null;
      const b = bubble.getBoundingClientRect();
      const c = content.getBoundingClientRect();
      const t = time.getBoundingClientRect();
      return {
        gap: t.top - c.bottom,
        bottomInset: b.bottom - t.bottom,
        contained: t.left >= b.left - 1 && t.right <= b.right + 1 &&
          t.top >= b.top - 1 && t.bottom <= b.bottom + 1,
      };
    }).filter(Boolean));
  for (const timestamp of timestamps) {
    stats.chatTimestamps += 1;
    check(timestamp.contained, `${label} message timestamp containment`,
      JSON.stringify(timestamp));
    check(timestamp.gap <= 7.5 && timestamp.bottomInset <= 16,
      `${label} message timestamp spacing`, JSON.stringify(timestamp));
  }

  const semantics = await page.evaluate(() => ({
    identityLabel: document.querySelector('#mobilePersonaIdentity').getAttribute('aria-label'),
    moreLabel: document.querySelector('#mobileHeaderMore').getAttribute('aria-label'),
    plusLabel: document.querySelector('#composerPlusBtn').getAttribute('aria-label'),
    inputLabel: document.querySelector('#msg').getAttribute('aria-label'),
    sendLabel: document.querySelector('#send').getAttribute('aria-label'),
    logRole: document.querySelector('#chat').getAttribute('role'),
  }));
  check(Object.values(semantics).every(Boolean), `${label} chat TalkBack labels`,
    JSON.stringify(semantics));
}

async function runCase(browser, viewport, theme, scale) {
  const [width, height] = viewport;
  const label = `${width}x${height}/${theme}/${scale * 100}%`;
  if (process.env.DIVAN_ACCEPTANCE_PROGRESS) console.error(`START ${label}`);
  const context = await browser.newContext({
    viewport: { width, height },
    colorScheme: theme === 'dark' ? 'dark' : 'light',
    reducedMotion: 'reduce',
    hasTouch: true,
    isMobile: true,
  });
  await context.addInitScript(({ selectedTheme, selectedScale }) => {
    window.DivanAndroid = {};
    try {
      localStorage.setItem('mobileTheme', selectedTheme);
      localStorage.setItem('fontScale', String(selectedScale));
      localStorage.setItem('reduceMotion', '1');
      localStorage.setItem('chatWallpaperMode', 'none');
      localStorage.setItem('autoNight', '0');
      localStorage.setItem('simpleMode', '0');
    } catch (_) {}
  }, { selectedTheme: theme, selectedScale: scale });
  const page = await context.newPage();
  page.setDefaultTimeout(10_000);
  try {
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#mobileHome:not([hidden])');
    check(await page.locator('body').evaluate((body) =>
      body.classList.contains('nativeAndroid') &&
      body.classList.contains('reduceMotion')),
    `${label} native/reduced-motion classes`);
    check(await page.locator('body').getAttribute('data-mobile-theme') === theme,
      `${label} applied theme`);
    check(await page.locator('html').evaluate((element) =>
      getComputedStyle(element).getPropertyValue('--fs').trim()) === String(scale),
    `${label} applied font scale`);
    await checkHome(page, THEMES[theme], label);
    await checkSettings(page, label);
    await checkChat(page, label);
    stats.cases += 1;
    if (process.env.DIVAN_ACCEPTANCE_PROGRESS) console.error(`PASS ${label}`);
  } catch (error) {
    failures.push(`${label} uncaught: ${error.stack || error}`);
    if (process.env.DIVAN_ACCEPTANCE_PROGRESS) console.error(`ERROR ${label}: ${error}`);
  } finally {
    await context.close();
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of VIEWPORTS) {
      for (const theme of Object.keys(THEMES)) {
        for (const scale of SCALES) {
          await runCase(browser, viewport, theme, scale);
        }
      }
    }
  } finally {
    await browser.close();
  }
  const report = { ...stats, failures: failures.length };
  console.log(JSON.stringify(report, null, 2));
  if (failures.length) {
    console.error(failures.slice(0, 100).join('\n'));
    if (failures.length > 100)
      console.error(`... ${failures.length - 100} more failures`);
    process.exitCode = 1;
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
