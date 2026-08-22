# PDI User Experience

PDI v1.0 uses a restrained, document-first interface. The visual system exists to clarify source authority, review scope, and provenance—not to make machine-derived information appear more certain than it is.

## Design system

- The canvas is a neutral off-white; source and work surfaces are white; green is reserved for primary navigation, grounded links, and calm confirmed states.
- Violet identifies metadata review, amber identifies extraction choices or caution, and blue identifies knowledge review. Red remains reserved for errors and destructive/reject affordances.
- Shared tokens in `apps/web/app/globals.css` define canvas, surfaces, text, borders, accent, radii, and panel elevation. Shared component classes define page widths, fields, panels, headings, status pills, and empty states.
- Typography uses the local system stack. No remote fonts, analytics, trackers, or content services are loaded.
- Motion is limited to short navigation, hover, progress, and loading feedback. `prefers-reduced-motion` disables non-essential animation and smooth scrolling.

## Navigation and retrieval

The desktop sidebar is fixed for the full viewport and grouped into Library and Knowledge. Narrow layouts use a modal drawer. “Ask PDI” is absent because conversational/RAG functionality is outside v1.0.

The top-bar **Search PDI** field always performs global lexical retrieval over confirmed metadata and canonical extracted text. The Documents field is labeled **Filter documents** and only narrows the currently loaded archive list by title or filename. These roles must remain distinct.

## Document experience

Document Detail prioritizes the immutable source file. PDF files render in the PDI viewer using locally bundled PDF.js with authenticated same-origin delivery. Controls include previous/next page, page count, zoom, fit width, fit page, fullscreen, and original download. Image files use the same protected delivery and explicit download behavior.

Evidence links append a source page to Document Detail. Search snippets, metadata proposals, knowledge proposals, Timeline events, and Upcoming obligations use this behavior. Exact quotes are displayed beside their page reference. Text highlighting is intentionally absent: stored evidence offsets refer to extracted text and cannot yet be mapped reliably to PDF glyph coordinates. PDI never implies a highlight that it cannot prove.

## Review semantics

Review is organized into three visually separate trust layers:

- **Metadata** (violet): field-scoped proposals and explicit document completion.
- **Extraction** (amber): selection of the canonical text version used by search and downstream analysis.
- **Knowledge** (blue): evidence-backed entities, contracts, events, deadlines, and actions.

Accept, edit, and reject remain proposal-scoped. **Mark document reviewed** remains the only metadata document-completion action. Extraction candidates never become canonical automatically.

Keyboard shortcuts are disabled while typing. In document review, J/K navigates between documents and Shift+Enter submits explicit completion. When a proposal card has focus, A accepts, E edits, and R rejects that field only. Search supports J/K plus Enter.

Extraction comparison uses human terms and displays text match, coverage, character change, critical-value preservation, and a bounded difference summary for amounts, dates, and identifier-like values. This summary is derived read-only from existing extraction versions; it is a review aid, not an authority decision.

## Responsive and accessibility baseline

- Long titles use truncation or bounded line clamping with the full value in `title` where appropriate.
- Dense grids collapse to source-first summaries at narrow widths; viewer overflow remains inside the viewer rather than the page.
- Controls have accessible names, native semantics, visible focus indicators, and minimum practical target sizes.
- Dialogs retain Radix focus management and Escape behavior.
- Loading, empty, error, duplicate, retry, and success states use consistent calm language and always state whether source documents are safe.

## Performance and privacy

PDF.js is loaded only on PDF Document Preview mounts. Only the selected page is rendered, capped at 2× device pixel density; resizing rerenders that page rather than the entire document. Search and archive list behavior remain server-paginated. All document and worker assets are bundled locally and protected document requests continue through the authenticated Next.js proxy.

## Known UX limitations

- Reliable PDF text highlighting and thumbnail strips are not implemented. Page navigation and exact quotes are the trustworthy fallback.
- There is no density selector or user-customizable theme.
- Settings/operational status remains intentionally absent from the browser UI.
- Collection pagination controls remain limited to Search until representative volumes require them elsewhere.
