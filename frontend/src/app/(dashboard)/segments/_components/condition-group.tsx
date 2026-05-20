"use client";

import { Button } from "@/components/ui/button";
import {
  ALLOWED_FIELDS,
  OPERATORS_BY_TYPE,
  getFieldDef,
  type SegmentGroup,
  type SegmentPredicate,
  type SegmentOperator,
} from "@/types/segment";

const MAX_DEPTH = 3;

type SegmentNode = SegmentPredicate | SegmentGroup;

function emptyPredicate(): SegmentPredicate {
  return { type: "predicate", field: "lifecycle_status", op: "eq", value: "active" };
}

function emptyGroup(): SegmentGroup {
  return { type: "group", logic: "and", conditions: [emptyPredicate()] };
}

function defaultValueForField(field: string): SegmentPredicate["value"] {
  const def = getFieldDef(field);
  if (!def) return "";
  if (def.type === "boolean") return true;
  if (def.type === "number") return 0;
  if (def.type === "enum" && def.options?.[0]) return def.options[0];
  return "";
}

type PredicateRowProps = {
  predicate: SegmentPredicate;
  onChange: (p: SegmentPredicate) => void;
  onRemove: () => void;
  removable: boolean;
  rowLabel: string;
};

function PredicateRow({
  predicate,
  onChange,
  onRemove,
  removable,
  rowLabel,
}: PredicateRowProps) {
  const fieldDef = getFieldDef(predicate.field);
  const operators = fieldDef ? OPERATORS_BY_TYPE[fieldDef.type] : [];

  function handleFieldChange(field: string) {
    const def = getFieldDef(field);
    const newOp = def ? (OPERATORS_BY_TYPE[def.type][0]?.value ?? "eq") : "eq";
    onChange({
      ...predicate,
      field,
      op: newOp as SegmentOperator,
      value: defaultValueForField(field),
    });
  }

  function handleOpChange(op: string) {
    let value = predicate.value;
    if (op === "in" && !Array.isArray(value)) {
      value = [String(value)];
    } else if (op !== "in" && Array.isArray(value)) {
      value = value[0] ?? "";
    }
    onChange({ ...predicate, op: op as SegmentOperator, value });
  }

  function handleValueChange(value: SegmentPredicate["value"]) {
    onChange({ ...predicate, value });
  }

  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="group"
      aria-label={rowLabel}
    >
      {/* Field select */}
      <select
        className="field h-9 min-w-40 max-w-xs"
        aria-label="Condition field"
        value={predicate.field}
        onChange={(e) => handleFieldChange(e.target.value)}
      >
        {ALLOWED_FIELDS.map((f) => (
          <option key={f.field} value={f.field}>
            {f.label}
          </option>
        ))}
      </select>

      {/* Operator select */}
      <select
        className="field h-9 min-w-32 max-w-xs"
        aria-label="Condition operator"
        value={predicate.op}
        onChange={(e) => handleOpChange(e.target.value)}
      >
        {operators.map((op) => (
          <option key={op.value} value={op.value}>
            {op.label}
          </option>
        ))}
      </select>

      {/* Value input */}
      <ValueInput
        predicate={predicate}
        fieldDef={fieldDef}
        onChange={handleValueChange}
      />

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onRemove}
        disabled={!removable}
        aria-label="Remove condition"
      >
        ✕
      </Button>
    </div>
  );
}

type ValueInputProps = {
  predicate: SegmentPredicate;
  fieldDef: ReturnType<typeof getFieldDef>;
  onChange: (value: SegmentPredicate["value"]) => void;
};

function ValueInput({ predicate, fieldDef, onChange }: ValueInputProps) {
  if (!fieldDef) return null;

  if (fieldDef.type === "boolean") {
    return (
      <select
        className="field h-9 min-w-24"
        aria-label="Condition value"
        value={String(predicate.value)}
        onChange={(e) => onChange(e.target.value === "true")}
      >
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }

  if (fieldDef.type === "enum" && fieldDef.options) {
    if (predicate.op === "in") {
      const selected = Array.isArray(predicate.value) ? predicate.value : [String(predicate.value)];
      return (
        <select
          className="field h-9 min-w-40"
          aria-label="Condition value"
          multiple
          size={Math.min(fieldDef.options.length, 4)}
          value={selected}
          onChange={(e) => {
            const opts = Array.from(e.target.selectedOptions).map((o) => o.value);
            onChange(opts);
          }}
        >
          {fieldDef.options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      );
    }
    return (
      <select
        className="field h-9 min-w-36"
        aria-label="Condition value"
        value={String(predicate.value)}
        onChange={(e) => onChange(e.target.value)}
      >
        {fieldDef.options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    );
  }

  if (fieldDef.type === "number") {
    return (
      <input
        type="number"
        className="field h-9 w-28"
        aria-label="Condition value"
        value={Number(predicate.value)}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    );
  }

  return (
    <input
      type="text"
      className="field h-9 min-w-40"
      aria-label="Condition value"
      placeholder="value…"
      value={String(predicate.value)}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

type ConditionGroupProps = {
  group: SegmentGroup;
  onChange: (group: SegmentGroup) => void;
  onRemove?: () => void;
  depth: number;
};

export function ConditionGroup({
  group,
  onChange,
  onRemove,
  depth,
}: ConditionGroupProps) {
  function updateCondition(index: number, updated: SegmentNode) {
    const conditions = [...group.conditions];
    conditions[index] = updated;
    onChange({ ...group, conditions });
  }

  function removeCondition(index: number) {
    onChange({
      ...group,
      conditions: group.conditions.filter((_, i) => i !== index),
    });
  }

  function addPredicate() {
    onChange({
      ...group,
      conditions: [...group.conditions, emptyPredicate()],
    });
  }

  function addGroup() {
    onChange({
      ...group,
      conditions: [...group.conditions, emptyGroup()],
    });
  }

  const canNest = depth < MAX_DEPTH;

  return (
    <div
      className={`grid gap-3 rounded-lg border border-border p-4 ${
        depth > 0 ? "bg-surface-muted/40" : "bg-transparent"
      }`}
      role="group"
      aria-label={`Condition group (${group.logic.toUpperCase()})`}
    >
      {/* Logic toggle + remove group */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1 rounded-md border border-border p-1">
          <button
            type="button"
            aria-pressed={group.logic === "and"}
            onClick={() => onChange({ ...group, logic: "and" })}
            className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
              group.logic === "and"
                ? "bg-primary primary-contrast"
                : "text-text-muted hover:text-foreground"
            }`}
          >
            AND
          </button>
          <button
            type="button"
            aria-pressed={group.logic === "or"}
            onClick={() => onChange({ ...group, logic: "or" })}
            className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
              group.logic === "or"
                ? "bg-primary primary-contrast"
                : "text-text-muted hover:text-foreground"
            }`}
          >
            OR
          </button>
        </div>

        <span className="text-xs text-text-muted">
          Match {group.logic === "and" ? "all" : "any"} of the following:
        </span>

        {onRemove ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onRemove}
            className="ml-auto"
            aria-label="Remove group"
          >
            Remove group
          </Button>
        ) : null}
      </div>

      {/* Conditions */}
      <div className="grid gap-2">
        {group.conditions.map((cond, i) => {
          if (cond.type === "group") {
            return (
              <ConditionGroup
                key={i}
                group={cond}
                onChange={(updated) => updateCondition(i, updated)}
                onRemove={() => removeCondition(i)}
                depth={depth + 1}
              />
            );
          }
          return (
            <PredicateRow
              key={i}
              predicate={cond}
              rowLabel={`Condition ${i + 1}`}
              onChange={(updated) => updateCondition(i, updated)}
              onRemove={() => removeCondition(i)}
              removable={group.conditions.length > 1}
            />
          );
        })}
      </div>

      {/* Add buttons */}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addPredicate}
        >
          + Add condition
        </Button>
        {canNest ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addGroup}
          >
            + Add group
          </Button>
        ) : null}
      </div>
    </div>
  );
}
