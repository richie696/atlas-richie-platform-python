import { Button, type ButtonSize, type ButtonVariant } from "@astryxdesign/core/Button";
import { isValidElement, type ButtonHTMLAttributes, type ReactNode } from "react";

/** Shared button contract that maps the prototype's semantic classes to Astryx. */
export type ActionButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "disabled" | "children"> & {
  children: ReactNode;
  disabled?: boolean;
  label?: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  isIconOnly?: boolean;
  isLoading?: boolean;
};

function textContent(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textContent).join(" ").trim();
  if (isValidElement(node)) return textContent((node.props as { children?: ReactNode }).children);
  return "";
}

/** Astryx-backed action button preserving existing Dashboard class hooks. */
export function ActionButton({ children, label, variant, size = "md", isIconOnly, isLoading, disabled = false, className, type = "button", ...rest }: ActionButtonProps) {
  const resolvedVariant = variant ?? (className?.includes("primary-button") ? "primary" : className?.includes("link-button") ? "ghost" : "secondary");
  const accessibleLabel = label ?? rest["aria-label"] ?? (textContent(children) || "Action");
  return <Button {...rest} type={type} className={className} label={accessibleLabel} variant={resolvedVariant} size={size} isDisabled={disabled} isIconOnly={isIconOnly} isLoading={isLoading}>{children}</Button>;
}
