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
  'console:cluster:delete': ['admin'],
  'console:machine:query': ['admin', 'operator'],
  'console:machine:create': ['admin'],
  'console:machine:update': ['admin'],
  'console:machine:delete': ['admin'],
  'console:machine:operate': ['admin'],
  'console:token:query': ['admin', 'operator'],
  'console:lb:query': ['admin', 'operator'],
  'console:lb:rule:write': ['admin'],
  'console:release:query': ['admin', 'operator'],
  'console:release:write': ['admin'],
  'console:audit:query': ['admin', 'operator'],
  'console:audit:export': ['admin'],
  'console:agent:enroll': ['admin', 'operator'],
  'console:callback:query': ['admin', 'operator'],
  'console:callback:manage': ['admin'],
  'console:template:query': ['admin', 'operator'],
  'console:template:create': ['admin'],
  'console:template:update': ['admin'],
  'console:template:delete': ['admin'],
  'console:smart:analyze': ['admin', 'operator'],
  'console:tool:query': ['admin', 'operator'],
  'console:tool:create': ['admin', 'operator'],
  'console:tool:update': ['admin', 'operator'],
  'console:tool:delete': ['admin', 'operator']
}

export function roleHasPermission(role: string, code: string): boolean {
  return PERMISSION_ROLES[code]?.includes(role) ?? false
}