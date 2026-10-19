# Architecture

Usher runs locally on the user's machine. Nothing is submitted automatically, and personal values stay on the machine except where noted below.

## Components

**Workbench.** A local web UI where the user keeps their profile and reviews per-job briefs. Starting an application from it is next.

**Resume engine.** Builds the resume from LaTeX and renders a PDF.

**Advisory brief.** An evidence base of the user's experience, each item with a stable id. For a posting, the model writes a brief (can I apply, where I match, a resume plan, essay drafts) that cites evidence by id, so every claim traces back to something real. Before the request, references' names, links, emails and phone numbers are replaced by placeholders; the job posting, including the company name, is sent as is.

**Generic form filler.**
1. *Scan.* Walk every frame of the application page and turn each control into a card: label, control type, options, required flag. Hidden helper inputs are skipped.
2. *Map.* One batched call per page to a small model. For each card it answers a profile key, `none` or `sensitive`. Structured output, refusal handling, and a second model only for fields that do not read back correctly.
3. *Fill.* Executors for text, native and custom dropdowns, phone country pickers and file upload put the real value in locally. Options are chosen by clicking.
4. *Guard.* Four guards are armed before the first action and stay on throughout; see [design-notes.md](design-notes.md).
5. *Hand over.* Guards come off, a report lists what was filled and what needs the user, and the browser stays open for the user to review and submit.

**Ledger and outcome rules.** Every application is recorded in an encrypted local database. Outcome emails are classified by sender, subject and date rules. No email content goes to a model.

## Where data goes

| Data | Leaves the machine? |
|---|---|
| Field labels and options | yes, to the mapping model |
| Name, email, phone, links | no |
| City, school, major | yes, with the dropdown options, to two models that must agree |
| Sponsorship, gender, ethnicity, veteran, disability, consent | never filled automatically |
| Work authorization | filled only from your recorded answer, only when the question names the country; not sent to a model |
| Pronouns | filled only from your recorded value; not sent to a model |
| Uploaded file names | never in reports or model calls |
| Email content | no |
| Experience descriptions (for drafting) | yes, to the advisor, with references, links, emails and phones replaced by placeholders |
| Job posting text and company name (for drafting) | yes, to the advisor |
| Drafts | used only after you approve them, each paragraph citing your evidence |
