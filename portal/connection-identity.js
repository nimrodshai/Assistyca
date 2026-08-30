// Whose account a connection is, and what it can do.
//
// These are two questions and neither answers the other. Gmail and Outlook are
// both the email platform, so a platform does not name a vendor; Google owns
// three platforms, so a vendor does not name a platform. Code that asked one
// while meaning the other is what deleted an Outlook mailbox during a Google
// disconnect, and what let a Google card call itself connected because a
// Microsoft mailbox existed.
//
// Nothing in here reads the page or the app's state, which is the point: these
// are the decisions those bugs lived in, and tests/connection_identity.test.mjs
// runs them directly under node. Anything needing `state` or the DOM belongs in
// app.js and should call in here for the answer.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module !== null && module.exports) {
    module.exports = api;
  } else {
    Object.assign(root, api);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  // Deliberately not shared with app.js's copy: this file loads first, and a
  // module that reaches back into the page for a helper is no longer testable
  // on its own.
  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  // What a connection can do. Several providers can share one of these.
  const EMAIL_PLATFORM = "email";
  const CALENDAR_PLATFORM = "calendar";
  const DRIVE_PLATFORM = "drive";

  // Whose account it is.
  const EMAIL_PROVIDER_GMAIL = "google_gmail";
  const EMAIL_PROVIDER_OUTLOOK = "microsoft_outlook";
  const CALENDAR_PROVIDER_GOOGLE = "google_calendar";
  const DRIVE_PROVIDER_GOOGLE = "google_drive";

  const EMAIL_PROVIDER_LABELS = {
    [EMAIL_PROVIDER_GMAIL]: "Gmail",
    [EMAIL_PROVIDER_OUTLOOK]: "Outlook",
  };

  // Which vendor each provider belongs to. Belonging is a property of the
  // provider and never of the platform. One table, so that adding a provider
  // is a line here rather than an audit of every place that groups things.
  const VENDOR_GOOGLE = "google";
  const VENDOR_MICROSOFT = "microsoft";
  const CONNECTION_VENDOR_BY_PROVIDER = {
    [EMAIL_PROVIDER_GMAIL]: VENDOR_GOOGLE,
    [CALENDAR_PROVIDER_GOOGLE]: VENDOR_GOOGLE,
    [DRIVE_PROVIDER_GOOGLE]: VENDOR_GOOGLE,
    [EMAIL_PROVIDER_OUTLOOK]: VENDOR_MICROSOFT,
  };

  // What a row on these platforms must be when it names no provider of its
  // own. Rows predate the provider being recorded, and these platforms have
  // only ever held Google's. The email platform is deliberately absent: it is
  // the one platform where a guess picks a vendor, and picking wrong deletes
  // someone's credential.
  const DEFAULT_PROVIDER_BY_PLATFORM = {
    [CALENDAR_PLATFORM]: CALENDAR_PROVIDER_GOOGLE,
    [DRIVE_PLATFORM]: DRIVE_PROVIDER_GOOGLE,
  };

  // What a vendor is called when a sentence has to name one.
  const VENDOR_LABELS = {
    [VENDOR_GOOGLE]: "Google",
    [VENDOR_MICROSOFT]: "Microsoft",
  };

  // What one platform is called in a list of things about to be removed. Not
  // the shelf's label: a calendar connection is drawn as "Google" there, which
  // in a list of Google things to remove says nothing at all.
  const PLATFORM_LABELS = {
    [CALENDAR_PLATFORM]: "Calendar",
    [DRIVE_PLATFORM]: "Drive",
    [EMAIL_PLATFORM]: "Email",
  };

  function getPlatformConnectionPlatformId(connection) {
    return String(connection?.platform || connection?.id || "").trim().toLowerCase();
  }

  // What the connection itself says its provider is, with no default. A caller
  // deciding what to delete needs to tell "Gmail" apart from "this row never
  // said", which every default below hides.
  function getPlatformConnectionProvider(connection) {
    const metadata = connection?.metadata && typeof connection.metadata === "object"
      ? connection.metadata
      : {};
    return normalizeText(connection?.provider || metadata.provider).toLowerCase();
  }

  // The provider a connection must be, falling back to its platform's only
  // one. Separate from the reader above because the fallback is a guess: fine
  // for naming a calendar, not fine for deciding what to delete. It stays
  // empty for a mailbox that names no provider, which is the one case where
  // guessing picks a vendor.
  function getResolvedPlatformConnectionProvider(connection) {
    return getPlatformConnectionProvider(connection)
      || DEFAULT_PROVIDER_BY_PLATFORM[getPlatformConnectionPlatformId(connection)]
      || "";
  }

  // Which vendor owns a connection, or "" when nothing here can say. An empty
  // answer is a real answer, and callers must treat it as "not this vendor"
  // rather than falling back to one.
  function getPlatformConnectionVendor(connection) {
    return CONNECTION_VENDOR_BY_PROVIDER[getResolvedPlatformConnectionProvider(connection)] || "";
  }

  // The question every grouped action has to ask before it acts on a vendor as
  // a whole: counting it connected, drawing it on the shelf, disconnecting it.
  function isVendorOwnedPlatformConnection(connection, vendor) {
    const wanted = normalizeText(vendor).toLowerCase();
    return Boolean(wanted) && getPlatformConnectionVendor(connection) === wanted;
  }

  function isOutlookPlatformConnection(connection) {
    return getPlatformConnectionPlatformId(connection) === EMAIL_PLATFORM
      && getPlatformConnectionProvider(connection) === EMAIL_PROVIDER_OUTLOOK;
  }

  // The provider a mailbox is shown as. Gmail is the default because it was
  // the only mailbox provider before Outlook, so a row naming none is one of
  // those. Naming a mailbox is all this is for - use the readers above to
  // decide anything.
  function getEmailConnectionProvider(connection) {
    return getPlatformConnectionProvider(connection) === EMAIL_PROVIDER_OUTLOOK
      ? EMAIL_PROVIDER_OUTLOOK
      : EMAIL_PROVIDER_GMAIL;
  }

  // What to call one mailbox: its address if the provider let us read it, else
  // a name the user gave it, else the provider.
  function getEmailConnectionName(connection) {
    return normalizeText(connection?.accountAddress)
      || normalizeText(connection?.accountLabel)
      || EMAIL_PROVIDER_LABELS[getEmailConnectionProvider(connection)]
      || "Email";
  }

  // One button removes several connections at once, so the confirmation names
  // them. Listing what a vendor can do rather than what this account has is
  // how a mailbox gets removed by someone who never knew it was included.
  function describeConnectionsToDisconnect(connections = []) {
    const mailboxes = [];
    const permissions = [];
    for (const connection of Array.isArray(connections) ? connections : []) {
      const platform = getPlatformConnectionPlatformId(connection);
      if (platform === EMAIL_PLATFORM) {
        mailboxes.push(`the mailbox ${getEmailConnectionName(connection)}`);
      } else {
        permissions.push(PLATFORM_LABELS[platform] || normalizeText(connection?.label) || platform);
      }
    }
    // Permissions first, mailboxes last: the mailbox is the surprising one,
    // and the end of the sentence is where it is read.
    const names = [...permissions, ...mailboxes].filter(Boolean);
    if (names.length <= 1) {
      return names[0] || "";
    }
    return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  }

  return {
    EMAIL_PLATFORM,
    CALENDAR_PLATFORM,
    DRIVE_PLATFORM,
    EMAIL_PROVIDER_GMAIL,
    EMAIL_PROVIDER_OUTLOOK,
    CALENDAR_PROVIDER_GOOGLE,
    DRIVE_PROVIDER_GOOGLE,
    EMAIL_PROVIDER_LABELS,
    VENDOR_GOOGLE,
    VENDOR_MICROSOFT,
    VENDOR_LABELS,
    CONNECTION_VENDOR_BY_PROVIDER,
    DEFAULT_PROVIDER_BY_PLATFORM,
    PLATFORM_LABELS,
    getPlatformConnectionPlatformId,
    getPlatformConnectionProvider,
    getResolvedPlatformConnectionProvider,
    getPlatformConnectionVendor,
    isVendorOwnedPlatformConnection,
    isOutlookPlatformConnection,
    getEmailConnectionProvider,
    getEmailConnectionName,
    describeConnectionsToDisconnect,
  };
});
