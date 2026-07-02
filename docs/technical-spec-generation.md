# Technical / Product Spec Generation

This repository keeps a separate internal spec flow for implementation and product planning.

## Where It Lives

- `clients/_template/technical-spec/spec.json` is the reusable starter template.
- `clients/<client-id>/technical-spec/spec.json` is the filled technical/product spec.
- `clients/<client-id>/technical-spec/spec.pdf` is the internal PDF.
- `scripts/generate_tech_product_spec_json.py` scaffolds a starter JSON file.
- `scripts/generate_tech_product_spec_pdf.py` renders the PDF from JSON.

## Workflow

1. Copy the technical-spec folder into a client folder or run the JSON generator.
2. Fill in the JSON fields with the product goals, architecture, data model, and implementation plan.
3. Run the PDF generator.
4. Review the rendered PDF before using it for implementation planning.
5. Update the JSON when the implementation shape changes, then regenerate the PDF.

## Example

```bash
python3 scripts/generate_tech_product_spec_json.py clients/Dor/technical-spec/spec.json \
  --client-name Dor \
  --project-name "WhatsApp Conversation Tracker, Reply Assistant, and Follow-up Reminder" \
  --prepared-by Codex \
  --date 2026-07-01
```

Render the PDF:

```bash
python3 scripts/generate_tech_product_spec_pdf.py clients/Dor/technical-spec/spec.json
```

## Fields

The generator expects this shape:

- `meta`
- `overview`
- `sections`

The `overview` object may include:

- `problem_statement`
- `product_goal`
- `recommended_shape`
- `implementation_notes`

The `sections` object may include:

- `goals`
- `architecture`
- `data_model`
- `automation`
- `workflows`
- `implementation_plan`
- `non_goals`
- `acceptance_criteria`
- `risks`
- `open_questions`
- `future_ideas`

## Notes

- This spec is for internal implementation planning, not client approval.
- Keep the source JSON under version control so product and technical decisions are easy to review.
- The PDF renderer reuses the same branded layout as the client-facing spec, but omits the approval block.
