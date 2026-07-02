# Spec PDF Generation

This repository uses a reusable JSON spec plus a PDF generator script to lock client scope before implementation.

For the internal technical/product version, see [docs/technical-spec-generation.md](/Users/nimrodshai/Documents/Projects/AgentsForAll/docs/technical-spec-generation.md).

## Where It Lives

- `clients/_template/spec/spec.json` is the reusable starter template.
- `clients/<client-id>/spec/spec.json` is the filled client spec.
- `clients/<client-id>/spec/spec.pdf` is the approval PDF.
- `scripts/generate_spec_pdf.py` renders the PDF from JSON.

## Workflow

1. Copy the template spec folder into a new client folder.
2. Fill in the JSON fields with the client's request and deliverables.
3. Run the generator script.
4. Share the PDF with the client for review and approval.
5. Treat anything not listed in the spec as needing an updated spec before implementation.

## Example

```bash
python3 scripts/generate_spec_pdf.py clients/Dor/spec/spec.json
```

To write the PDF somewhere else:

```bash
python3 scripts/generate_spec_pdf.py clients/Dor/spec/spec.json --output /tmp/Dor-spec.pdf
```

## Fields

The generator expects this shape:

- `meta`
- `overview`
- `sections`
- `approval`

The `sections` object may include:

- `deliverables`
- `workflow`
- `assumptions`
- `open_questions`
- `acceptance_criteria`
- `future_ideas`

## Notes

- The same spec structure should work for future clients.
- The PDF generator automatically places `assets/AssistycaLogo.png` in the page header.
- When list items are prefixed with `Tool 1:` or `Tool 2:`, the generator collapses them into tool headers with grouped bullets or numbered workflows.
- Update the JSON when scope changes, then regenerate the PDF.
- Keep the source JSON under version control so scope changes are easy to review.
