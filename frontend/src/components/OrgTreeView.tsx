import { useEffect, useRef, type ReactNode } from "react";
import type { OrgTreeEmployee, OrgTreeNode } from "../api/types";
import { collectDescendantIds, nodeExpandKey } from "./orgTreeUtils";

export type NodeCheckState = {
  checked: boolean;
  indeterminate: boolean;
  disabled: boolean;
};

type Props = {
  root: OrgTreeNode;
  expanded: Set<string>;
  onToggleExpand: (key: string) => void;
  /** When false, bots are hidden from the tree (default false). */
  includeBots?: boolean;
  /**
   * browse: expand-only org tab
   * select: multi-select picker with dept select-all checkboxes
   */
  mode?: "browse" | "select";
  selected?: Set<number>;
  exclude?: Set<number>;
  onToggleEmployee?: (id: number) => void;
  onToggleNode?: (node: OrgTreeNode) => void;
  nodeCheckState?: (node: OrgTreeNode) => NodeCheckState;
  /** Optional trailing control per employee row (e.g. favorite star). */
  renderEmployeeActions?: (emp: OrgTreeEmployee, deptName: string) => ReactNode;
  className?: string;
};

function NodeCheckbox({
  checked,
  indeterminate,
  disabled,
  onChange,
}: {
  checked: boolean;
  indeterminate: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate && !checked;
  }, [indeterminate, checked]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      disabled={disabled}
      onChange={onChange}
      onClick={(ev) => ev.stopPropagation()}
    />
  );
}

/**
 * Shared org tree: One2그룹 root, nested departments, expand/collapse.
 * Used by OrgUserPicker (select) and MessengerPage org tab (browse).
 */
export default function OrgTreeView({
  root,
  expanded,
  onToggleExpand,
  includeBots = false,
  mode = "browse",
  selected,
  exclude,
  onToggleEmployee,
  onToggleNode,
  nodeCheckState,
  renderEmployeeActions,
  className = "org-tree-vertical",
}: Props) {
  const excludeSet = exclude || new Set<number>();
  const selectedSet = selected || new Set<number>();

  function renderEmpRow(e: OrgTreeEmployee, deptName: string) {
    const disabled = excludeSet.has(e.id);
    if (mode === "browse") {
      return (
        <div key={e.id} className="org-picker-row org-browse-emp">
          <span className="org-picker-name">
            {e.name}
            <span className="muted small"> ({e.employee_id})</span>
          </span>
        </div>
      );
    }
    return (
      <div
        key={e.id}
        className={`org-picker-row ${selectedSet.has(e.id) ? "selected" : ""} ${disabled ? "disabled" : ""}`}
      >
        <label className="org-picker-check">
          <input
            type="checkbox"
            checked={selectedSet.has(e.id)}
            disabled={disabled}
            onChange={() => onToggleEmployee?.(e.id)}
          />
          <span className="org-picker-name">
            {e.name}
            {e.is_bot ? " 🤖" : ""}
            <span className="muted small"> ({e.employee_id})</span>
          </span>
        </label>
        {renderEmployeeActions?.(e, deptName)}
      </div>
    );
  }

  function renderDept(node: OrgTreeNode, depth: number) {
    const key = nodeExpandKey(node);
    const isOpen = expanded.has(key);
    const emps = (node.employees || []).filter((e) => includeBots || !e.is_bot);
    const check = mode === "select" && nodeCheckState ? nodeCheckState(node) : null;
    const count =
      mode === "select"
        ? collectDescendantIds(node, includeBots, excludeSet).length
        : (node.children || []).length + emps.length;

    return (
      <div key={key} className="org-tree-node" style={{ marginLeft: depth ? 12 : 0 }}>
        <div className="org-tree-header">
          {mode === "select" && check && (
            <label className="org-tree-node-check" title="하위 직원 전체 선택/해제">
              <NodeCheckbox
                checked={check.checked}
                indeterminate={check.indeterminate}
                disabled={check.disabled}
                onChange={() => onToggleNode?.(node)}
              />
            </label>
          )}
          <button type="button" className="org-tree-toggle" onClick={() => onToggleExpand(key)}>
            <span className="caret">{isOpen ? "▼" : "▶"}</span>
            <strong>{node.name}</strong>
            <span className="muted small"> ({count})</span>
          </button>
        </div>
        {isOpen && (
          <div className="org-tree-children org-tree-vertical">
            {/* Child organizations first (parent above children), then this unit's employees */}
            {(node.children || []).map((c) => renderDept(c, depth + 1))}
            {mode === "select"
              ? [
                  ...emps
                    .filter((e) => !excludeSet.has(e.id) || selectedSet.has(e.id))
                    .map((e) => renderEmpRow(e, node.name)),
                  ...emps
                    .filter((e) => excludeSet.has(e.id) && !selectedSet.has(e.id))
                    .map((e) => renderEmpRow(e, node.name)),
                ]
              : emps.map((e) => renderEmpRow(e, node.name))}
          </div>
        )}
      </div>
    );
  }

  return <div className={className}>{renderDept(root, 0)}</div>;
}
