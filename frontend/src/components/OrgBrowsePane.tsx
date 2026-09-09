import type { OrgTreeNode } from "../api/types";
import OrgTreeView from "./OrgTreeView";

type Props = {
  orgTree: OrgTreeNode | null;
  expanded: Set<string>;
  onToggleExpand: (key: string) => void;
  onOpenPicker: () => void;
};

/** Messenger org-tab pane: browse-only tree (shared OrgTreeView). */
export default function OrgBrowsePane({
  orgTree,
  expanded,
  onToggleExpand,
  onOpenPicker,
}: Props) {
  return (
    <div className="org-layout">
      <div className="org-layout-head">
        <h2>조직도</h2>
        <button type="button" className="secondary" onClick={onOpenPicker}>
          직원 선택
        </button>
      </div>
      <p className="muted small org-layout-hint">
        조직을 클릭하면 하위 조직·소속 직원이 펼쳐집니다. 기본은 접힌 상태입니다.
      </p>
      <div className="org-browse-tree">
        {orgTree ? (
          <OrgTreeView
            root={orgTree}
            expanded={expanded}
            onToggleExpand={onToggleExpand}
            includeBots={false}
            mode="browse"
            className="org-tree-vertical"
          />
        ) : (
          <div className="muted center" style={{ padding: "2rem" }}>
            조직도를 불러오는 중…
          </div>
        )}
      </div>
    </div>
  );
}
