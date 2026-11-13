/**
 * 后端 `app/core/permissions.py` 的 PERMISSION_ROLES 镜像（spec §4.4）。
 * 仅供前端少摆按钮；服务端每个端点仍独立校验，这里不是安全边界。
 * 改后端矩阵必须同步改这里，permissions.spec.ts 会拦住漂移。
 */
export const PERMISSION_ROLES: Record<string, readonly string[]> = {
  'console:cluster:query': ['admin', 'operator'],
  'console:cluster:switch': ['admin', 'operator'],
  'console:cluster:create': ['admin'],
  'console:cluster:update': ['admin'],
  'console:cluster:delete': ['admin']
}

export function roleHasPermission(role: string, code: string): boolean {
  return PERMISSION_ROLES[code]?.includes(role) ?? false
}