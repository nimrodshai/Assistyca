# Family billing

How a family pays to keep the assistant once the free trial is over
(`docs/free-trials.md` covers the trial itself).

## What the family sees

- While the trial runs, the price is never brought up for its own sake. It is
  answered when they ask what it costs or how to pay, and said once, in a
  line at the end of a reply, in the last three days.
- When the trial has ended, the assistant says so in a line or two and sends
  the payment link, with the price. Deleting the account and disconnecting
  stay open whether or not they pay.
- The link is `/pay/<code>`. Opening it makes a fresh Lemon Squeezy checkout
  for that account and sends the browser on to it. After paying, the
  checkout returns them to WhatsApp.
- An account that already pays is sent by the same link to Lemon Squeezy's
  page for managing or cancelling the subscription, so a second tap never
  buys twice.

## How a payment finds its account

A family account has no email, so the payment is never matched by the
address typed at checkout. The checkout carries the account id in its custom
data, and Lemon Squeezy repeats it on every subscription event. The payment
code is the account id plus a signature made with the session secret, so a
link can only ever pay for its own account and nothing has to be stored.

`POST /webhooks/lemon-squeezy` receives the subscription events, checks the
`X-Signature` against `LEMON_SQUEEZY_SIGNING_SECRET`, and writes the
subscription into `billing_customers` for that account.

## What counts as paying

`family_billing.subscription_is_paying`: `active`, `on_trial` and `past_due`
(a renewal whose card is being retried) pay; `cancelled` pays until its
`ends_at`; anything else does not.

## Setting it up

1. In Lemon Squeezy: a store, a product "Assistyca" with one subscription
   variant at the price, monthly.
2. Settings > API: an API key. Settings > Webhooks: a webhook to
   `https://<public address>/webhooks/lemon-squeezy` with a signing secret, and
   the `subscription_*` events ticked.
3. On Render: `LEMON_SQUEEZY_API_KEY`, `LEMON_SQUEEZY_STORE_ID`,
   `LEMON_SQUEEZY_VARIANT_ID`, `LEMON_SQUEEZY_SIGNING_SECRET`,
   `ASSISTYCA_PRICE_LABEL` ("$4.90 a month"), and `LEMON_SQUEEZY_TEST_MODE`
   (`true` on staging).

Until the store and variant are set, `payment_link` says payment is not open
yet and the assistant does not mention the trial or the price.
