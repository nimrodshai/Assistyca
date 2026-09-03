# Free Trials

A new account may use Assistyca for a fixed number of days before it has to
pay. Days rather than messages, because days are what you can quote to a client
and what they can plan around.

## The rule

An account is allowed to use the agent when **any** of these is true:

* it is paying (an active subscription in `billing_customers`), or
* its trial length is `0`, which means no limit, or
* its trial is still running.

Everything else is refused before a model is called, so a finished trial costs
nothing rather than costing slightly less. The three paths that reach a model —
the conversation turn, the lookup runner, and the answer composer — each check
this, and they all return `402` with `error: "trial_expired"`. The browser shows
that message in the chat; the WhatsApp flow sends it as an ordinary message,
because the person reading it is a client whose trial ran out, not a caller who
did something wrong.

## Length is per account

`users.trial_days` holds the length and `users.trial_started_at` holds the
clock. They are separate on purpose: extending a trial that is already running
should not hand back the days already spent, so raising the length leaves the
start where it is. Restarting is asked for explicitly.

`0` means unlimited, and it is what every account created before trials existed
carries — introducing this cannot switch off a client who is already working.

## Setting it

* The clients screen in the portal shows where each account stands and takes
  the length in days beside it. Setting `0` there removes the limit.
  Restarting the clock is not offered on that screen.
* `POST /api/admin/users/<email>/trial` with `{"trialDays": 14}` sets the
  length. `{"trialDays": 0}` removes the limit; `{"restart": true}` also
  restarts the clock.
* `PORTAL_DEFAULT_TRIAL_DAYS` is the length a newly created account starts on.
  It defaults to `2`.

Every admin user record carries a `trial` object (`onTrial`, `allowed`,
`expired`, `trialDays`, `endsAt`, `daysLeft`) so the client list can show where
each account stands.

## Tests

`tests/test_trial_access.py` covers the rule itself and its enforcement;
`tests/test_whatsapp_agent_chat.py` covers what an expired trial sounds like on
a phone.
