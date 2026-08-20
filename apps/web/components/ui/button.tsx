import * as React from "react";
import { cn } from "@/lib/utils";

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" };

export function Button({ className, variant = "primary", ...props }: Props) {
  return (
    <button
      className={cn(
        "inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 disabled:pointer-events-none disabled:opacity-50",
        variant === "primary"
          ? "bg-stone-900 text-white shadow-sm hover:bg-stone-800"
          : "border border-stone-200 bg-white text-stone-700 hover:bg-stone-50",
        className,
      )}
      {...props}
    />
  );
}

