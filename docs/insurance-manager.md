# Insurance manager

The insurance manager keeps both sides of a policy:

- The original file or exact supplied text is the authority.
- The structured summary is the fast index used to find candidate coverage.

The two are stored separately on an immutable policy version. Renewals and
endorsements append versions; they do not overwrite the wording that applied
to an older receipt.

## Policy shape

`insurance_policies` holds the stable identity the owner recognises: insurer,
masked policy-number hint, policy type, covered subject, and current status.

`insurance_policy_versions` holds:

- effective dates;
- a plain-language summary;
- structured coverage, limits, deductibles, conditions, exclusions, and claim
  deadlines;
- evidence section/page pointers and short excerpts;
- review status;
- original bytes or exact source text, plus a SHA-256 digest.

Original bytes and source text are omitted from normal list and chat results.
They can only be read through an owner-scoped source lookup. Deleting the
account cascades through the policy versions and their sources.

## Receipt screening

Every receipt included in an answer or written to a receipt bundle is screened
against the account's saved policies. Screening:

1. Normalizes the date, amount, currency, vendor, subject, and expense hints.
2. Selects the immutable policy version in force on the receipt date.
3. Ranks matching structured coverage categories.
4. Compares the receipt amount with a same-currency deductible when possible.
5. Carries the supporting section/page pointer, conditions, exclusions, and
   an estimated filing date into the result. The estimate is explicitly based
   on the receipt date and must be checked against the policy's actual trigger.

The manifest stores an `insuranceCheck` beside every documented receipt, even
when there is no match. Excel and PDF exports include potential-claim notices.
Receipts kept on the receipts page are screened again when they are shown or
exported, so a policy saved later can reveal a potential claim on an older
receipt. Manually entered receipts follow the same path.

## Result meanings

- `likely_worth_claiming`: category match, source document and evidence pointer
  are present, the structured interpretation was reviewed, and no recorded
  condition or exclusion still needs review.
- `possible_more_information_needed`: the summary suggests a match but the
  original evidence, human review, or receipt date is missing, or event facts
  must still be checked against conditions or exclusions.
- `deductible_may_exceed_expense`: the receipt amount does not exceed the
  recorded same-currency deductible.
- `no_relevant_policy`: no saved policy version plausibly matches.

These are screening results, not insurer decisions. The assistant must never
call a claim approved or coverage guaranteed. Before filing, the user should
confirm the event facts, definitions, exclusions, deductible, notice deadline,
and the insurer's required documents.

## Assistant tools

- `save_insurance_policy` creates a policy or appends a version from supplied
  facts. If a policy photo is attached to the turn, the original image is
  preserved with the structured interpretation.
- `show_insurance_policies` lists the manager or reads one policy.
- `check_insurance_expense` screens one expense explicitly.
- `archive_insurance_policy` removes a policy from active matching while
  retaining its history.

Receipt and saved-folder lookups also run screening automatically, so a user
does not need to remember to ask about insurance separately.
