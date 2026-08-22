import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

class TestResizeObserver {
  constructor(private callback: ResizeObserverCallback) {}
  observe(target: Element) {
    this.callback(
      [{ target, contentRect: { width: 900, height: 700 } } as ResizeObserverEntry],
      this,
    );
  }
  disconnect() {}
  unobserve() {}
}

vi.stubGlobal("ResizeObserver", TestResizeObserver);
Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
  configurable: true,
  value: vi.fn(() => ({})),
});
Object.defineProperty(HTMLElement.prototype, "scrollTo", {
  configurable: true,
  value: vi.fn(),
});
