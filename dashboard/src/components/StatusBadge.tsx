import type { StatusValue } from "../types";
import { STATUS_META } from "../utils";

export function StatusBadge({ status }: { status: StatusValue }) {
  const meta = STATUS_META[status] ?? STATUS_META.unknown;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${meta.badge}`}
    >
      {meta.label}
    </span>
  );
}

export function StatusDot({ status }: { status: StatusValue }) {
  const meta = STATUS_META[status] ?? STATUS_META.unknown;
  return <span className={`inline-block h-2 w-2 rounded-full ${meta.dot}`} />;
}
