// The browser's half of "whose connection is this", run for real.
//
// The portal's behaviour has been pinned by asserting that certain text
// appears in app.js, which cannot catch a function that returns the wrong
// rows - and returning the wrong rows is what both mailbox bugs were. These
// call the code.
//
// Run by tests/test_portal_static_pages.py under `python3 -m unittest`, so
// they go green or red with everything else.

import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const identity = require(path.join(repoRoot, "portal", "connection-identity.js"));

const {
  EMAIL_PROVIDER_GMAIL,
  EMAIL_PROVIDER_OUTLOOK,
  VENDOR_GOOGLE,
  VENDOR_MICROSOFT,
  getPlatformConnectionProvider,
  getResolvedPlatformConnectionProvider,
  getPlatformConnectionVendor,
  isVendorOwnedPlatformConnection,
  isOutlookPlatformConnection,
  getEmailConnectionProvider,
  getEmailConnectionName,
  describeConnectionsToDisconnect,
} = identity;

const gmail = {
  id: "pc_gmail",
  platform: "email",
  provider: EMAIL_PROVIDER_GMAIL,
  authType: "oauth",
  accountAddress: "nimrod@gmail.com",
};
const outlook = {
  id: "pc_outlook",
  platform: "email",
  provider: EMAIL_PROVIDER_OUTLOOK,
  authType: "oauth",
  accountAddress: "nimrod@gmail.com",
};
const calendar = { id: "pc_cal", platform: "calendar", provider: "google_calendar", authType: "oauth" };
const drive = { id: "pc_drive", platform: "drive", provider: "google_drive", authType: "oauth" };

test("a mailbox belongs to the vendor of its provider, not of its platform", () => {
  assert.equal(getPlatformConnectionVendor(gmail), VENDOR_GOOGLE);
  assert.equal(getPlatformConnectionVendor(outlook), VENDOR_MICROSOFT);
  assert.equal(getPlatformConnectionVendor(calendar), VENDOR_GOOGLE);
  assert.equal(getPlatformConnectionVendor(drive), VENDOR_GOOGLE);
});

test("disconnecting one vendor never reaches the other's mailbox", () => {
  // The bug: this list decided what a single "Disconnect Google" button
  // deleted, and it was gathered by platform. Gmail and Outlook share the
  // email platform, so Outlook's credential went with Google's.
  const connected = [gmail, outlook, calendar, drive];

  const googles = connected.filter((c) => isVendorOwnedPlatformConnection(c, VENDOR_GOOGLE));
  assert.deepEqual(googles.map((c) => c.id), ["pc_gmail", "pc_cal", "pc_drive"]);

  const microsofts = connected.filter((c) => isVendorOwnedPlatformConnection(c, VENDOR_MICROSOFT));
  assert.deepEqual(microsofts.map((c) => c.id), ["pc_outlook"]);
});

test("a vendor with nothing connected is not connected, whoever else is", () => {
  // With only Outlook connected, the Google card called itself connected and
  // offered to disconnect a mailbox Google never held.
  assert.equal([outlook].some((c) => isVendorOwnedPlatformConnection(c, VENDOR_GOOGLE)), false);
});

test("a mailbox that names no provider belongs to no vendor", () => {
  // Both platforms with a single provider fall back to it; email does not,
  // because there the fallback would pick a vendor and a wrong pick deletes a
  // credential.
  const unnamedMailbox = { id: "pc_old", platform: "email", authType: "oauth" };
  const unnamedCalendar = { id: "pc_oldcal", platform: "calendar", authType: "oauth" };

  assert.equal(getPlatformConnectionVendor(unnamedMailbox), "");
  assert.equal(isVendorOwnedPlatformConnection(unnamedMailbox, VENDOR_GOOGLE), false);
  assert.equal(isVendorOwnedPlatformConnection(unnamedMailbox, VENDOR_MICROSOFT), false);
  assert.equal(getResolvedPlatformConnectionProvider(unnamedCalendar), "google_calendar");
  assert.equal(getPlatformConnectionVendor(unnamedCalendar), VENDOR_GOOGLE);
});

test("a row written before the provider column still names its provider", () => {
  const legacy = { id: "pc_legacy", platform: "email", metadata: { provider: EMAIL_PROVIDER_OUTLOOK } };

  assert.equal(getPlatformConnectionProvider(legacy), EMAIL_PROVIDER_OUTLOOK);
  assert.equal(getPlatformConnectionVendor(legacy), VENDOR_MICROSOFT);
  assert.equal(isOutlookPlatformConnection(legacy), true);
  assert.equal(isVendorOwnedPlatformConnection(legacy, VENDOR_GOOGLE), false);
});

test("the column wins over the metadata when a row carries both", () => {
  const migrated = {
    platform: "email",
    provider: EMAIL_PROVIDER_OUTLOOK,
    metadata: { provider: EMAIL_PROVIDER_GMAIL },
  };

  assert.equal(getPlatformConnectionProvider(migrated), EMAIL_PROVIDER_OUTLOOK);
});

test("naming a mailbox falls back to Gmail, deciding about one never does", () => {
  const unnamed = { platform: "email", accountAddress: "someone@example.com" };

  // Shown as Gmail, because Gmail was the only mailbox provider before Outlook.
  assert.equal(getEmailConnectionProvider(unnamed), EMAIL_PROVIDER_GMAIL);
  // But that display default must not put it in Google's delete list.
  assert.equal(isVendorOwnedPlatformConnection(unnamed, VENDOR_GOOGLE), false);
});

test("two mailboxes sharing one address are still told apart", () => {
  assert.equal(getEmailConnectionName(gmail), getEmailConnectionName(outlook));
  assert.notEqual(getPlatformConnectionVendor(gmail), getPlatformConnectionVendor(outlook));
});

test("a mailbox is named by address, then label, then provider", () => {
  assert.equal(getEmailConnectionName({ platform: "email", accountAddress: "a@b.com", accountLabel: "Work" }), "a@b.com");
  assert.equal(getEmailConnectionName({ platform: "email", accountLabel: "Work" }), "Work");
  assert.equal(getEmailConnectionName({ platform: "email", provider: EMAIL_PROVIDER_OUTLOOK }), "Outlook");
});

test("the confirmation names what it removes, mailbox last", () => {
  assert.equal(
    describeConnectionsToDisconnect([calendar, drive, gmail]),
    "Calendar, Drive and the mailbox nimrod@gmail.com",
  );
  assert.equal(describeConnectionsToDisconnect([calendar, drive]), "Calendar and Drive");
  assert.equal(describeConnectionsToDisconnect([calendar]), "Calendar");
  assert.equal(describeConnectionsToDisconnect([]), "");
});

test("a calendar is named Calendar, not the Google its shelf tile says", () => {
  // The shelf draws a calendar connection as "Google", and a list of Google
  // things to remove that says "Google" names nothing.
  assert.equal(describeConnectionsToDisconnect([{ ...calendar, label: "Google" }]), "Calendar");
});

test("nothing here falls over on a connection that is missing or empty", () => {
  for (const value of [null, undefined, {}, { platform: "" }]) {
    assert.equal(getPlatformConnectionProvider(value), "");
    assert.equal(getPlatformConnectionVendor(value), "");
    assert.equal(isVendorOwnedPlatformConnection(value, VENDOR_GOOGLE), false);
  }
  assert.equal(isVendorOwnedPlatformConnection(gmail, ""), false);
  assert.equal(describeConnectionsToDisconnect(null), "");
});
