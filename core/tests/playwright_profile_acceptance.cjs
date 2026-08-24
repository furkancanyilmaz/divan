const { chromium } = require('playwright');

const BASE = process.env.DIVAN_TEST_URL || 'http://127.0.0.1:8879/';
const viewports = [
  { width: 320, height: 568, label: '320x568' },
  { width: 568, height: 320, label: '568x320' },
];
const themes = ['white', 'paper', 'dark'];
const people = [
  {
    name: 'Sigmund Freud', role: 'Terapist', views: 'Temel görüşler',
    methods: 'Terapi yöntemleri', lifespan: '1856–1939',
    boundary: ['Tanı, tedavi', 'acil destek'],
  },
  {
    name: 'Sokrates', role: 'Felsefeci',
    views: 'Temel görüşler ve argümanlar',
    methods: 'Felsefi soru ve metin yolları', lifespan: 'y. MÖ 469–399',
    boundary: ['Doğrudan alıntı', 'uzman görüşü'],
  },
  {
    name: 'ADHD Koçu', role: 'Koç', views: 'Temel yaklaşım',
    methods: 'Koçluk odakları', lifespan: null,
    boundary: ['kurgusal', 'Tanı, tedavi'],
  },
];

const failures = [];
const measurements = [];
function check(condition, message, details = {}) {
  if (!condition) failures.push({ message, ...details });
}

async function enterConversation(page, name) {
  await page.locator('#mobileHome').waitFor({ state: 'visible' });
  const row = page.locator('.mobileConversationItem').filter({ hasText: name }).first();
  await row.waitFor({ state: 'visible' });
  await row.click();
  await page.locator('#mobilePersonaIdentity').waitFor({ state: 'visible' });
}

async function openProfile(page) {
  await page.locator('#mobilePersonaIdentity').click();
  await page.locator('#mobileMasterProfileOverlay.show').waitFor({ state: 'visible' });
  await page.locator('#mobileMasterProfileContent').waitFor({ state: 'visible' });
  await page.waitForFunction(() =>
    document.querySelector('#mobileMasterProfileOverlay')?.getAttribute('aria-busy') === 'false');
  await page.waitForTimeout(30);
}

async function measureProfile(page) {
  return page.evaluate(() => {
    const q = (selector) => document.querySelector(selector);
    const rect = (selector) => {
      const r = q(selector).getBoundingClientRect();
      return {
        x: r.x, y: r.y, right: r.right, bottom: r.bottom,
        width: r.width, height: r.height,
      };
    };
    const text = q('#mobileMasterProfileScroll').innerText;
    const views = [...q('#mobileMasterProfileViews').querySelectorAll('li')]
      .map((node) => node.innerText.trim()).filter(Boolean);
    const approaches = [...q('#mobileMasterProfileApproaches').querySelectorAll('li')]
      .map((node) => node.innerText.trim()).filter(Boolean);
    const normalized = (value) => value.toLocaleLowerCase('tr-TR')
      .replace(/\s+/g, ' ').trim();
    const approachKeys = new Set(approaches.map(normalized));
    return {
      viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio },
      page: rect('#mobileMasterProfileOverlay .mobileMasterProfilePage'),
      header: rect('#mobileMasterProfileOverlay .mobileMasterProfileHeader'),
      scroll: rect('#mobileMasterProfileScroll'),
      back: rect('#mobileMasterProfileBack'),
      documentOverflow: document.documentElement.scrollWidth - innerWidth,
      profileOverflow: q('#mobileMasterProfileScroll').scrollWidth -
        q('#mobileMasterProfileScroll').clientWidth,
      activeElement: document.activeElement?.id || '',
      regionRole: q('#mobileMasterProfileScroll').getAttribute('role'),
      regionLabel: q('#mobileMasterProfileScroll').getAttribute('aria-label'),
      regionTabIndex: q('#mobileMasterProfileScroll').tabIndex,
      bodyTheme: document.body.dataset.mobileTheme,
      fontScale: getComputedStyle(document.documentElement)
        .getPropertyValue('--fs').trim(),
      reducedMotionClass: document.body.classList.contains('reduceMotion'),
      pageTransition: getComputedStyle(q('#mobileMasterProfileOverlay .mobileMasterProfilePage'))
        .transitionDuration,
      name: q('#mobileMasterProfileName').innerText.trim(),
      meta: q('#mobileMasterProfileMeta').innerText.trim(),
      subtitle: q('#mobileMasterProfileSubtitle').innerText.trim(),
      lifespan: q('#mobileMasterProfileLifespan').innerText.trim(),
      lifespanHidden: q('#mobileMasterProfileLifespan').hidden,
      viewsTitle: q('#mobileMasterProfileViewsTitle').innerText.trim(),
      methodsTitle: q('#mobileMasterProfileApproachesTitle').innerText.trim(),
      views, approaches,
      overlap: views.filter((item) => approachKeys.has(normalized(item))),
      missingVisible: !q('#mobileMasterProfileMissing').hidden,
      boundary: q('#mobileMasterProfileBoundary').innerText.trim(),
      text,
    };
  });
}

async function runMatrix(browser) {
  for (const viewport of viewports) {
    for (const theme of themes) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        deviceScaleFactor: 2,
        reducedMotion: 'reduce',
      });
      await context.addInitScript(({ theme }) => {
        localStorage.setItem('mobileTheme', theme);
        localStorage.setItem('fontScale', '2');
        localStorage.setItem('reduceMotion', '1');
      }, { theme });
      const page = await context.newPage();
      await page.goto(BASE, { waitUntil: 'domcontentloaded' });
      await page.locator('#mobileHome').waitFor({ state: 'visible' });

      for (const person of people) {
        await enterConversation(page, person.name);
        await openProfile(page);
        const m = await measureProfile(page);
        const tag = `${viewport.label}/${theme}/200%/${person.name}`;
        measurements.push({ tag, ...m });

        check(m.viewport.dpr === 2, 'DPR %200 değil', { tag, value: m.viewport.dpr });
        check(m.fontScale === '2', 'Metin ölçeği %200 değil', { tag, value: m.fontScale });
        check(m.bodyTheme === theme, 'Tema uygulanmadı', { tag, value: m.bodyTheme });
        check(m.reducedMotionClass && m.pageTransition === '0s',
          'Azaltılmış hareket uygulanmadı', { tag, value: m.pageTransition });
        check(Math.abs(m.page.x) < 0.1 && Math.abs(m.page.width - viewport.width) < 0.1,
          'Profil sayfası kenardan kenara değil', { tag, rect: m.page });
        check(Math.abs(m.header.x) < 0.1 && Math.abs(m.header.width - viewport.width) < 0.1,
          'Profil başlığı kenardan kenara değil', { tag, rect: m.header });
        check(m.documentOverflow <= 0.5 && m.profileOverflow <= 0.5,
          'Yatay taşma var', { tag, document: m.documentOverflow, profile: m.profileOverflow });
        check(m.back.width >= 48 && m.back.height >= 48,
          'Geri hedefi 48x48 değil', { tag, rect: m.back });
        check(m.activeElement === 'mobileMasterProfileScroll',
          'Başarılı yükleme odağı profil bölgesinde değil', { tag, value: m.activeElement });
        check(m.regionRole === 'region' && m.regionLabel === 'Usta profil bilgileri' &&
          m.regionTabIndex === 0, 'Kaydırma bölgesi erişilebilir değil', { tag });
        check(m.name === person.name && m.meta.startsWith(`${person.role} ·`),
          'Rol veya isim yanlış', { tag, name: m.name, meta: m.meta });
        check(m.viewsTitle === person.views && m.methodsTitle === person.methods,
          'Rol tabanlı bölüm başlığı yanlış', {
            tag, views: m.viewsTitle, methods: m.methodsTitle,
          });
        check(m.views.length > 0 && m.approaches.length > 0 && m.overlap.length === 0,
          'Görüş/yöntem listeleri boş veya yineleniyor', {
            tag, views: m.views, approaches: m.approaches, overlap: m.overlap,
          });
        check(!m.missingVisible, 'Eksik veri uyarısı beklenmeden göründü', { tag });
        for (const phrase of person.boundary) {
          check(m.boundary.includes(phrase), 'AI sınırı eksik', { tag, phrase, boundary: m.boundary });
        }
        if (person.lifespan) {
          check(m.lifespan === person.lifespan && !m.lifespanHidden,
            'Yaşam tarihi yanlış/gizli', { tag, lifespan: m.lifespan });
          check((m.text.match(new RegExp(person.lifespan.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length === 1,
            'Yaşam tarihi birden fazla gösteriliyor', { tag, text: m.text });
        } else {
          check(m.lifespanHidden && m.lifespan === '',
            'Olmayan yaşam tarihi uyduruldu', { tag, lifespan: m.lifespan });
        }

        if (viewport.label === '568x320' && theme === 'paper' &&
            person.name === 'Sigmund Freud') {
          const beforeScroll = await page.locator('#mobileMasterProfileScroll')
            .evaluate((node) => node.scrollTop);
          await page.keyboard.press('PageDown');
          await page.waitForTimeout(30);
          const afterScroll = await page.locator('#mobileMasterProfileScroll')
            .evaluate((node) => node.scrollTop);
          check(afterScroll > beforeScroll,
            'Klavye ile profil kaydırılamıyor', { tag, beforeScroll, afterScroll });
        }

        await page.locator('#mobileMasterProfileBack').click();
        await page.locator('#mobileMasterProfileOverlay').waitFor({ state: 'hidden' });
        await page.waitForFunction(() =>
          document.activeElement?.id === 'mobilePersonaIdentity');
        const focusAfterBack = await page.evaluate(() => document.activeElement?.id || '');
        check(focusAfterBack === 'mobilePersonaIdentity',
          'Geri dönüş odağı usta kimliğine dönmedi', { tag, value: focusAfterBack });
        await page.locator('#mobileBackBtn').click();
        await page.locator('#mobileHome').waitFor({ state: 'visible' });
      }
      await context.close();
    }
  }
}

async function runErrorRetry(browser) {
  const context = await browser.newContext({
    viewport: { width: 320, height: 568 },
    deviceScaleFactor: 2,
    reducedMotion: 'reduce',
  });
  await context.addInitScript(() => {
    localStorage.setItem('mobileTheme', 'dark');
    localStorage.setItem('fontScale', '2');
    localStorage.setItem('reduceMotion', '1');
  });
  const page = await context.newPage();
  let requests = 0;
  await page.route('**/api/master-profile*', async (route) => {
    requests += 1;
    if (requests <= 2) {
      await new Promise((resolve) => setTimeout(resolve, 120));
      await route.fulfill({
        status: 503,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify({ error: 'Kontrollü profil hatası' }),
      });
      return;
    }
    await route.continue();
  });
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await enterConversation(page, 'Sigmund Freud');
  await page.locator('#mobilePersonaIdentity').click();
  await page.locator('#mobileMasterProfileOverlay.show').waitFor({ state: 'visible' });

  const loading = await page.evaluate(() => ({
    busy: document.querySelector('#mobileMasterProfileOverlay').getAttribute('aria-busy'),
    statusVisible: !document.querySelector('#mobileMasterProfileStatus').hidden,
    status: document.querySelector('#mobileMasterProfileStatus').innerText,
  }));
  check(loading.busy === 'true' && loading.statusVisible && loading.status === 'Profil yükleniyor…',
    'Yükleme durumu erişilebilir değil', { loading });

  await page.locator('#mobileMasterProfileError').waitFor({ state: 'visible' });
  await page.waitForTimeout(30);
  let errorState = await page.evaluate(() => ({
    active: document.activeElement?.id || '',
    visibleAlerts: [...document.querySelectorAll('[role="alert"]')]
      .filter((node) => node.checkVisibility({
        checkOpacity: true, checkVisibilityCSS: true,
      })).length,
    toastShown: document.querySelector('#toast')?.classList.contains('show') || false,
    text: document.querySelector('#mobileMasterProfileErrorText').innerText,
  }));
  check(errorState.active === 'mobileMasterProfileRetry',
    'Hata odağı yeniden dene düğmesinde değil', errorState);
  check(errorState.visibleAlerts === 1 && !errorState.toastShown,
    'Hata birden çok kez duyuruluyor', errorState);

  await page.locator('#mobileMasterProfileRetry').click();
  await page.locator('#mobileMasterProfileError').waitFor({ state: 'visible' });
  await page.waitForTimeout(30);
  errorState = await page.evaluate(() => ({ active: document.activeElement?.id || '' }));
  check(errorState.active === 'mobileMasterProfileRetry',
    'İkinci hata sonrası odak yeniden dene düğmesine dönmedi', errorState);

  await page.locator('#mobileMasterProfileRetry').click();
  await page.locator('#mobileMasterProfileContent').waitFor({ state: 'visible' });
  await page.waitForFunction(() =>
    document.querySelector('#mobileMasterProfileOverlay')?.getAttribute('aria-busy') === 'false');
  await page.waitForTimeout(30);
  const recovered = await page.evaluate(() => ({
    active: document.activeElement?.id || '',
    name: document.querySelector('#mobileMasterProfileName').innerText,
    errorHidden: document.querySelector('#mobileMasterProfileError').hidden,
  }));
  check(recovered.active === 'mobileMasterProfileScroll' &&
    recovered.name === 'Sigmund Freud' && recovered.errorHidden,
    'Yeniden deneme başarılı profile dönmedi', recovered);
  check(requests === 3, 'Yeniden deneme istek sayısı yanlış', { requests });
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    await runMatrix(browser);
    await runErrorRetry(browser);
  } finally {
    await browser.close();
  }
  const summary = {
    scenarios: measurements.length,
    viewportThemePairs: viewports.length * themes.length,
    profiles: people.length,
    errorRetryScenarios: 1,
    failures,
    sampleMeasurements: measurements.map((m) => ({
      tag: m.tag, page: m.page, header: m.header,
      overflow: [m.documentOverflow, m.profileOverflow],
      back: [m.back.width, m.back.height], activeElement: m.activeElement,
    })),
  };
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
  process.exitCode = failures.length ? 1 : 0;
})().catch((error) => {
  console.error(error);
  process.exitCode = 2;
});
