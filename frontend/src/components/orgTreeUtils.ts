import type { OrgTreeEmployee, OrgTreeNode } from "../api/types";

export type FlatEmp = OrgTreeEmployee & { departmentName: string };

export function nodeExpandKey(node: OrgTreeNode): string {
  return node.node_type === "group" ? "root" : `dept-${node.id}`;
}

export function flattenTree(node: OrgTreeNode, deptName = ""): FlatEmp[] {
  const here = node.node_type === "department" ? node.name : deptName;
  const list: FlatEmp[] = node.employees.map((e) => ({
    ...e,
    departmentName: here || node.name,
  }));
  for (const child of node.children || []) {
    list.push(...flattenTree(child, here || node.name));
  }
  return list;
}

/** Collect selectable employee ids under a node (direct + descendants). */
export function collectDescendantIds(
  node: OrgTreeNode,
  includeBots: boolean,
  exclude: Set<number>
): number[] {
  const ids: number[] = [];
  for (const e of node.employees || []) {
    if (!includeBots && e.is_bot) continue;
    if (exclude.has(e.id)) continue;
    ids.push(e.id);
  }
  for (const child of node.children || []) {
    ids.push(...collectDescendantIds(child, includeBots, exclude));
  }
  return ids;
}
