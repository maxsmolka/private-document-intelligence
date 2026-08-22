import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DocumentPreview } from "@/components/document-preview";
import * as pdfjs from "pdfjs-dist";

vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerSrc: "" },
  getDocument: vi.fn(),
}));

const fetchMock = vi.fn(async () => ({
  ok: true,
  arrayBuffer: async () => new ArrayBuffer(32),
}));
vi.stubGlobal("fetch", fetchMock);

function pdfDocument({ pages = 1, width = 600, height = 800, renderError = false } = {}) {
  const render = vi.fn(() => ({
    promise: renderError ? Promise.reject(new Error("synthetic render failure")) : Promise.resolve(),
    cancel: vi.fn(),
  }));
  const getPage = vi.fn(async () => ({
    getViewport: ({ scale }: { scale: number }) => ({ width: width * scale, height: height * scale }),
    render,
  }));
  return { numPages: pages, getPage, destroy: vi.fn(async () => undefined), render };
}

function mockPdf(document: ReturnType<typeof pdfDocument>) {
  vi.mocked(pdfjs.getDocument).mockReturnValue({ promise: Promise.resolve(document) } as unknown as ReturnType<typeof pdfjs.getDocument>);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DocumentPreview PDF rendering", () => {
  it.each([
    ["normal digital PDF", { pages: 1, width: 600, height: 800 }, 1],
    ["OCR PDF", { pages: 1, width: 612, height: 792 }, 1],
    ["rotated PDF", { pages: 1, width: 800, height: 600 }, 1],
    ["multi-page PDF", { pages: 4, width: 600, height: 800 }, 3],
    ["object-stream compatibility PDF", { pages: 2, width: 595, height: 842 }, 1],
  ])("renders a visible canvas for a %s", async (_name, options, initialPage) => {
    const document = pdfDocument(options);
    mockPdf(document);
    const { container } = render(<DocumentPreview documentId="document-id" mimeType="application/pdf" title="Fixture" heightClass="h-[700px]" initialPage={initialPage} />);
    await waitFor(() => expect(document.render).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText(/Rendering page/)).not.toBeInTheDocument());
    expect(document.getPage).toHaveBeenCalledWith(initialPage);
    const canvas = container.querySelector("canvas");
    expect(canvas).toBeVisible();
    expect(canvas?.width).toBeGreaterThan(0);
    expect(canvas?.height).toBeGreaterThan(0);
  });

  it("shows an explicit render failure with authenticated fallback and download", async () => {
    mockPdf(pdfDocument({ renderError: true }));
    render(<DocumentPreview documentId="document-id" mimeType="application/pdf" title="Fixture" heightClass="h-[700px]" />);
    expect(await screen.findByText("Preview could not be rendered in the enhanced viewer.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Download original" })).toHaveAttribute("href", "/api/pdi/api/v1/documents/document-id/content");
    fireEvent.click(screen.getByRole("button", { name: "Open fallback preview" }));
    expect(screen.getByTitle("Authenticated fallback PDF preview")).toHaveAttribute("src", "/api/pdi/api/v1/documents/document-id/content");
  });

  it("keeps page navigation, zoom, and fit controls rendering", async () => {
    const document = pdfDocument({ pages: 3 });
    mockPdf(document);
    render(<DocumentPreview documentId="document-id" mimeType="application/pdf" title="Fixture" heightClass="h-[700px]" />);
    await waitFor(() => expect(document.getPage).toHaveBeenCalledWith(1));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(document.getPage).toHaveBeenCalledWith(2));
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await waitFor(() => expect(document.render).toHaveBeenCalledTimes(3));
    fireEvent.click(screen.getByRole("button", { name: "Fit page" }));
    await waitFor(() => expect(document.render).toHaveBeenCalledTimes(4));
    fireEvent.click(screen.getByRole("button", { name: "Fit width" }));
    await waitFor(() => expect(document.render).toHaveBeenCalledTimes(5));
  });

  it("labels encrypted PDFs as unsupported instead of leaving a blank canvas", async () => {
    const error = Object.assign(new Error("password required"), { name: "PasswordException" });
    vi.mocked(pdfjs.getDocument).mockReturnValue({ promise: Promise.reject(error) } as unknown as ReturnType<typeof pdfjs.getDocument>);
    render(<DocumentPreview documentId="document-id" mimeType="application/pdf" title="Fixture" heightClass="h-[700px]" />);
    expect(await screen.findByText("This PDF needs the fallback preview.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Open fallback preview" })).toBeEnabled();
  });
});
