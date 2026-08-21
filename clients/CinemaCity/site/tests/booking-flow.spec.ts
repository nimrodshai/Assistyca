import { expect, test } from '@playwright/test';

test('desktop visitor can complete the demo booking flow', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto('/');
  await expect(page.getByRole('link', { name: /סינמה סיטי עמוד הבית/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'ספיידרמן: יום חדש' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'הציגו שעות' })).toBeEnabled();

  await page.getByRole('button', { name: 'הציגו שעות' }).click();
  await expect(page.getByRole('heading', { name: 'בוחרים הקרנה' })).toBeVisible();
  await page.getByRole('button', { name: /20:30/ }).click();
  await page.getByRole('button', { name: 'המשך לכרטיסים ומושבים' }).click();

  await expect(page.getByRole('heading', { name: 'בוחרים כרטיסים ומושבים' })).toBeVisible();
  await page.getByRole('button', { name: 'הוספת מבוגר' }).click();
  await page.getByRole('button', { name: 'הוספת מבוגר' }).click();
  await page.getByRole('button', { name: /שורה F, מושב 6/ }).click();
  await page.getByRole('button', { name: /שורה F, מושב 7/ }).click();
  await page.getByRole('button', { name: 'המשך לתשלום' }).click();

  await page.getByRole('textbox', { name: 'שם מלא' }).fill('לקוח הדגמה');
  await page.getByRole('textbox', { name: 'מייל' }).fill('demo@cinemacity.co.il');
  await page.getByRole('textbox', { name: 'טלפון נייד' }).fill('050-555-0182');
  await page.getByRole('checkbox', { name: /קראתי ואני מאשר/ }).check();
  await page.getByRole('button', { name: /אישור הזמנה מדומה/ }).click();

  await expect(page.getByRole('heading', { name: 'הכרטיסים שלכם מוכנים' })).toBeVisible();
  await expect(page.getByText(/CC-/)).toBeVisible();
  await expect(page.getByText('F6, F7')).toBeVisible();
});

test('mobile children filter opens a dubbed movie without horizontal page scroll', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/movies');
  await page.getByRole('checkbox', { name: 'לילדים' }).check();
  await page.getByRole('link', { name: /לוני טונס/ }).first().click();
  await expect(page.getByRole('heading', { name: /לוני טונס/ })).toBeVisible();
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
});

test('fixture order can be cancelled and remains cancelled after refresh', async ({ page }) => {
  await page.goto('/manage-order');
  await page.getByRole('button', { name: 'בדיקה' }).click();
  await expect(page.getByRole('heading', { name: /הזמנה CC-482731/ })).toBeVisible();
  await page.getByRole('button', { name: 'ביטול הזמנה' }).click();
  await page.getByRole('button', { name: 'ביטול הזמנה מדומה' }).click();
  await expect(page.getByLabel(/הזמנה CC-482731/).getByText('ההזמנה בוטלה בגרסת ההדגמה.')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'בדיקה' }).click();
  await expect(page.getByLabel(/הזמנה CC-482731/).getByText('בוטלה', { exact: true })).toBeVisible();
});
