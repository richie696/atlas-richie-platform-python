import type { SelectProps } from "../../../src/shared/ui/Select";
import type { RadioGroupOption } from "../../../src/shared/ui/RadioGroup";

type Role = "admin" | "view";
const roleOptions = [
  { value: "admin", label: "Admin" },
  { value: "view", label: "View" },
] as const;

/** Compile-only contract: unknown choices cannot silently widen a restricted selection callback. */
export function verifyChoiceContracts() {
  const valid: SelectProps<Role> = {
    label: "Role",
    value: "view",
    options: roleOptions,
    onChange: (role: Role) => void role,
  };
  const invalid: SelectProps<Role> = {
    ...valid,
    // @ts-expect-error An unsupported role is not made valid by its display label.
    options: [{ value: "owner", label: "Owner" }],
  };
  const numeric: SelectProps<Role> = {
    ...valid,
    // @ts-expect-error Numeric protocol values need a feature-owned conversion, not implicit UI coercion.
    options: [{ value: 1, label: "Admin" }],
  };
  const radio: RadioGroupOption<Role> = {
    // @ts-expect-error Radio options obey the same identity set as Select.
    value: "owner",
    label: "Owner",
  };
  return { valid, invalid, numeric, radio };
}
