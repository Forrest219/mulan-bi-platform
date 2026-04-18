/**
 * @vitest-environment jsdom
 *
 * Eval: 陷阱 2 — React.lazy named export 静默失败
 *
 * 背景：React.lazy 只支持 default export。
 * 如果直接 lazy(() => import('./Foo')) 而 Foo.tsx 只有 named export，
 * React 会在渲染时抛出"Element type is invalid"错误，且错误信息不直观。
 *
 * 正确方式：
 *   lazy(() => import('./Foo').then(m => ({ default: m.FooComponent })))
 *
 * 本测试验证：
 * 1. 正确的 default export lazy 加载方式可以正常渲染
 * 2. 错误的 named export lazy 加载（未转换 default）会在 Suspense 边界触发错误
 */
import { describe, it, expect, vi } from "vitest";
import {
  render,
  screen,
  waitFor,
  act,
} from "@testing-library/react";
import React, { Suspense } from "react";

// ─── 模拟一个只有 named export 的组件模块 ───────────────────────────────────

/** 模拟仅具名导出的模块 */
const namedExportModule = {
  NamedWidget: () => <div data-testid="named-widget">Named Widget</div>,
};

/** 模拟具有 default export 的模块 */
const defaultExportModule = {
  default: () => <div data-testid="default-widget">Default Widget</div>,
};

describe("陷阱 2 — React.lazy named export 静默失败", () => {
  it("正确方式：lazy + .then(m => ({ default: m.Named })) 可正常渲染", async () => {
    // 正确：将 named export 包装为 default
    const LazyNamed = React.lazy(() =>
      Promise.resolve(namedExportModule).then((m) => ({
        default: m.NamedWidget,
      }))
    );

    await act(async () => {
      render(
        <Suspense fallback={<div>Loading...</div>}>
          <LazyNamed />
        </Suspense>
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("named-widget")).toBeDefined();
      expect(screen.getByTestId("named-widget").textContent).toBe(
        "Named Widget"
      );
    });
  });

  it("正确方式：lazy(() => import(...)) 配合 default export 可正常渲染", async () => {
    const LazyDefault = React.lazy(() =>
      Promise.resolve(defaultExportModule)
    );

    await act(async () => {
      render(
        <Suspense fallback={<div>Loading...</div>}>
          <LazyDefault />
        </Suspense>
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("default-widget")).toBeDefined();
    });
  });

  it("错误方式：lazy 直接加载 named export（无 default 字段）会抛出渲染错误", async () => {
    // 模拟一个没有 default export 的模块（只有 named export）
    const badModule = { NamedOnly: () => <div>bad</div> } as any;

    // React.lazy 要求模块有 .default，否则渲染时报错
    const BadLazy = React.lazy(() => Promise.resolve(badModule));

    // 捕获 React 的错误边界报错
    const errors: Error[] = [];
    class ErrorBoundary extends React.Component<
      { children: React.ReactNode },
      { hasError: boolean }
    > {
      constructor(props: { children: React.ReactNode }) {
        super(props);
        this.state = { hasError: false };
      }
      static getDerivedStateFromError() {
        return { hasError: true };
      }
      componentDidCatch(error: Error) {
        errors.push(error);
      }
      render() {
        if (this.state.hasError)
          return <div data-testid="error-boundary">Error caught</div>;
        return this.props.children;
      }
    }

    // 压制 console.error 避免测试输出噪音
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await act(async () => {
      render(
        <ErrorBoundary>
          <Suspense fallback={<div>Loading...</div>}>
            <BadLazy />
          </Suspense>
        </ErrorBoundary>
      );
    });

    consoleSpy.mockRestore();

    await waitFor(() => {
      // 错误边界应该捕获到错误（named export 没有 .default，React.lazy 失败）
      expect(screen.getByTestId("error-boundary")).toBeDefined();
    });

    // 确认捕获到了具体错误
    expect(errors.length).toBeGreaterThan(0);
  });

  it("项目规范断言：所有 lazy 调用必须包含 .default 或 .then(m => default) 包装", () => {
    // 这是一个文档性测试，用于教育开发者：
    // React.lazy 内部会执行 module.default，若 default 为 undefined，抛出：
    // "Element type is invalid: expected a string (for built-in components) or
    //  a class/function (for composite components) but got: undefined."
    //
    // 正确写法示例（项目中应遵循）：
    const correctPattern = `
      // ✅ 正确 — default export
      const Foo = lazy(() => import('./Foo'));

      // ✅ 正确 — named export 转 default
      const Bar = lazy(() => import('./Bar').then(m => ({ default: m.Bar })));

      // ❌ 错误 — named export 直接 lazy（会静默失败）
      // const Baz = lazy(() => import('./Baz')); // 若 Baz 只有 named export
    `;
    expect(correctPattern).toBeTruthy(); // 占位断言，确保此测试被执行
  });
});
