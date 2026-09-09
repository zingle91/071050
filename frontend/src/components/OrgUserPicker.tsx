import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Employee, OrgTreeNode } from "../api/types";
import OrgTreeView from "./OrgTreeView";
import {
  collectDescendantIds,
  flattenTree,
  type FlatEmp,
} from "./orgTreeUtils";

export type PickedUser = {
  id: number;
  employee_id: string;
  name: string;
  is_bot: boolean;
};

type Props = {
  open: boolean;
  title?: string;
  /** Confirm button label */
  confirmLabel?: string;
  /** Max number of selectable users; omit for unlimited */
  maxSelect?: number;
  /** Employee ids that cannot be selected */
  excludeIds?: number[];
  /** Include AI bots in the tree (default false) */
  includeBots?: boolean;
  initialSelectedIds?: number[];
  onClose: () => void;
  onConfirm: (users: PickedUser[]) => void;
};

export default function OrgUserPicker({
  open,
  title = "직원 선택",
  confirmLabel = "확인",
  maxSelect,
  excludeIds = [],
  includeBots = false,
  initialSelectedIds = [],
  onClose,
  onConfirm,
}: Props) {
  const [tab, setTab] = useState<"org" | "fav">("org");
  const [query, setQuery] = useState("");
  const [tree, setTree] = useState<OrgTreeNode | null>(null);
  const [favorites, setFavorites] = useState<Employee[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["root"]));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const exclude = useMemo(() => new Set(excludeIds), [excludeIds]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [t, f] = await Promise.all([
        api<OrgTreeNode>("/api/org/tree"),
        api<Employee[]>("/api/org/favorites"),
      ]);
      setTree(t);
      setFavorites(f);
      // Only root (One2그룹) open by default; departments stay collapsed
      // so employees appear only after the user expands a unit.
      setExpanded(new Set<string>(["root"]));
    } catch (e) {
      setError(e instanceof Error ? e.message : "조직도를 불러오지 못했습니다");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setTab("org");
    setSelected(new Set(initialSelectedIds));
    load().catch(console.error);
    // Only re-init when dialog opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, load]);

  const allFlat = useMemo(() => {
    if (!tree) return [];
    return flattenTree(tree).filter((e) => includeBots || !e.is_bot);
  }, [tree, includeBots]);

  const empById = useMemo(() => {
    const byId = new Map<number, FlatEmp>();
    for (const e of allFlat) byId.set(e.id, e);
    for (const f of favorites) {
      if (!byId.has(f.id)) {
        byId.set(f.id, {
          id: f.id,
          employee_id: f.employee_id,
          name: f.name,
          is_bot: f.is_bot,
          is_favorite: true,
          departmentName: f.department?.name || "",
        });
      }
    }
    return byId;
  }, [allFlat, favorites]);

  const favSet = useMemo(() => {
    const s = new Set<number>();
    for (const e of allFlat) if (e.is_favorite) s.add(e.id);
    for (const e of favorites) s.add(e.id);
    return s;
  }, [allFlat, favorites]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    return allFlat.filter((e) => {
      if (exclude.has(e.id)) return false;
      return (
        e.name.toLowerCase().includes(q) ||
        e.employee_id.toLowerCase().includes(q) ||
        e.departmentName.toLowerCase().includes(q)
      );
    });
  }, [query, allFlat, exclude]);

  function toggleExpand(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function addIds(prev: Set<number>, ids: number[]): Set<number> {
    const next = new Set(prev);
    for (const id of ids) {
      if (exclude.has(id)) continue;
      if (next.has(id)) continue;
      if (maxSelect === 1) {
        return new Set([id]);
      }
      if (maxSelect && next.size >= maxSelect) break;
      next.add(id);
    }
    return next;
  }

  function toggleSelect(id: number) {
    if (exclude.has(id)) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        return next;
      }
      return addIds(prev, [id]);
    });
  }

  /** Check parent = select all descendants; uncheck = clear those descendants. */
  function toggleNodeSelect(node: OrgTreeNode) {
    const ids = collectDescendantIds(node, includeBots, exclude);
    if (!ids.length) return;
    setSelected((prev) => {
      const allOn = ids.every((id) => prev.has(id));
      if (allOn) {
        const next = new Set(prev);
        for (const id of ids) next.delete(id);
        return next;
      }
      return addIds(prev, ids);
    });
  }

  function nodeCheckState(node: OrgTreeNode): {
    checked: boolean;
    indeterminate: boolean;
    disabled: boolean;
  } {
    const ids = collectDescendantIds(node, includeBots, exclude);
    if (!ids.length) return { checked: false, indeterminate: false, disabled: true };
    const selectedCount = ids.filter((id) => selected.has(id)).length;
    return {
      checked: selectedCount === ids.length,
      indeterminate: selectedCount > 0 && selectedCount < ids.length,
      disabled: false,
    };
  }

  async function toggleFavorite(empId: number, currentlyFav: boolean) {
    try {
      const list = currentlyFav
        ? await api<Employee[]>(`/api/org/favorites/${empId}`, { method: "DELETE" })
        : await api<Employee[]>("/api/org/favorites", {
            method: "POST",
            body: JSON.stringify({ employee_id: empId }),
          });
      setFavorites(list);
      const t = await api<OrgTreeNode>("/api/org/tree");
      setTree(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : "즐겨찾기 변경 실패");
    }
  }

  function confirm() {
    const users: PickedUser[] = [...selected]
      .map((id) => empById.get(id))
      .filter(Boolean)
      .map((e) => ({
        id: e!.id,
        employee_id: e!.employee_id,
        name: e!.name,
        is_bot: e!.is_bot,
      }));
    onConfirm(users);
  }

  function removeChip(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }

  if (!open) return null;

  const selectedCount = selected.size;
  const selectedUsers = [...selected]
    .map((id) => empById.get(id))
    .filter(Boolean) as FlatEmp[];

  function renderEmpRowSearch(
    e: FlatEmp | (Employee & { departmentName?: string }),
    showDept = false
  ) {
    const disabled = exclude.has(e.id);
    const fav = favSet.has(e.id);
    const deptName =
      "departmentName" in e && e.departmentName
        ? e.departmentName
        : "department" in e && e.department
          ? e.department?.name || ""
          : "";
    return (
      <div
        key={e.id}
        className={`org-picker-row ${selected.has(e.id) ? "selected" : ""} ${disabled ? "disabled" : ""}`}
      >
        <label className="org-picker-check">
          <input
            type="checkbox"
            checked={selected.has(e.id)}
            disabled={disabled}
            onChange={() => toggleSelect(e.id)}
          />
          <span className="org-picker-name">
            {e.name}
            {e.is_bot ? " 🤖" : ""}
            <span className="muted small"> ({e.employee_id})</span>
            {showDept && deptName ? (
              <span className="muted small"> · {deptName}</span>
            ) : null}
          </span>
        </label>
        <button
          type="button"
          className={`star-btn ${fav ? "on" : ""}`}
          title={fav ? "즐겨찾기 해제" : "즐겨찾기 추가"}
          onClick={() => toggleFavorite(e.id, fav)}
        >
          {fav ? "★" : "☆"}
        </button>
      </div>
    );
  }

  const favList = favorites.filter((e) => {
    if (!includeBots && e.is_bot) return false;
    return true;
  });

  return (
    <div className="modal-overlay org-picker-overlay" onClick={onClose} role="presentation">
      <div
        className="org-picker-modal"
        onClick={(ev) => ev.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="org-picker-header">
          <h2>{title}</h2>
          <button type="button" className="ghost" onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </header>

        <div className="org-picker-search">
          <input
            autoFocus
            placeholder="이름, 사번, 부서 검색"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        <div className="org-picker-tabs">
          <button
            type="button"
            className={tab === "org" ? "active" : ""}
            onClick={() => setTab("org")}
          >
            조직도
          </button>
          <button
            type="button"
            className={tab === "fav" ? "active" : ""}
            onClick={() => setTab("fav")}
          >
            즐겨찾기
          </button>
        </div>

        {selectedUsers.length > 0 && (
          <div className="org-picker-chips">
            {selectedUsers.map((u) => (
              <span key={u.id} className="chip chip-removable">
                {u.name}
                <button
                  type="button"
                  className="chip-x"
                  aria-label={`${u.name} 선택 해제`}
                  onClick={() => removeChip(u.id)}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="org-picker-body">
          {loading && <div className="center muted">불러오는 중...</div>}
          {error && <div className="error">{error}</div>}

          {!loading && filtered && (
            <div className="org-search-results">
              <div className="muted small" style={{ marginBottom: 8 }}>
                검색 결과 {filtered.length}명
              </div>
              {filtered.length === 0 ? (
                <div className="muted">일치하는 결과가 없습니다</div>
              ) : (
                filtered.map((e) => renderEmpRowSearch(e, true))
              )}
            </div>
          )}

          {!loading && !filtered && tab === "org" && tree && (
            <OrgTreeView
              root={tree}
              expanded={expanded}
              onToggleExpand={toggleExpand}
              includeBots={includeBots}
              mode="select"
              selected={selected}
              exclude={exclude}
              onToggleEmployee={toggleSelect}
              onToggleNode={toggleNodeSelect}
              nodeCheckState={nodeCheckState}
              renderEmployeeActions={(e) => {
                const fav = favSet.has(e.id);
                return (
                  <button
                    type="button"
                    className={`star-btn ${fav ? "on" : ""}`}
                    title={fav ? "즐겨찾기 해제" : "즐겨찾기 추가"}
                    onClick={() => toggleFavorite(e.id, fav)}
                  >
                    {fav ? "★" : "☆"}
                  </button>
                );
              }}
            />
          )}

          {!loading && !filtered && tab === "fav" && (
            <div className="org-fav-list">
              {favList.length === 0 ? (
                <div className="muted center" style={{ padding: "2rem" }}>
                  즐겨찾기한 직원이 없습니다.
                  <br />
                  조직도에서 ★를 눌러 추가하세요.
                </div>
              ) : (
                favList.map((e) =>
                  renderEmpRowSearch(
                    {
                      id: e.id,
                      employee_id: e.employee_id,
                      name: e.name,
                      is_bot: e.is_bot,
                      is_favorite: true,
                      departmentName: e.department?.name || "",
                    },
                    true
                  )
                )
              )}
            </div>
          )}
        </div>

        <footer className="org-picker-footer">
          <div className="muted small">
            {selectedCount}명 선택
            {maxSelect ? ` (최대 ${maxSelect}명)` : ""}
          </div>
          <div className="org-picker-actions">
            <button type="button" className="secondary" onClick={onClose}>
              취소
            </button>
            <button type="button" onClick={confirm} disabled={selectedCount === 0}>
              {confirmLabel}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
