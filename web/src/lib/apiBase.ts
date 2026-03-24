/**
 * URL base do `telegram_manager` (rotas `/api/*`).
 *
 * Por defeito usa caminhos relativos (`/api/...`) — correto quando o painel e o
 * gestor são o mesmo host:porta (ex.: GET /dashboard e GET /api/stats no MANAGER_PORT).
 *
 * Se o painel for servido por outro processo/porta sem `/api`, faça build com:
 *   VITE_API_BASE=http://IP_OU_HOST:MANAGER_PORT
 * Ex.: VITE_API_BASE=http://37.27.25.179:8000
 */
export function getApiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE as string | undefined;
  if (raw == null || !String(raw).trim()) return "";
  return String(raw).trim().replace(/\/$/, "");
}

/** Ex.: apiUrl("/api/stats") → "/api/stats" ou "http://host:8000/api/stats" */
export function apiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const base = getApiBaseUrl();
  return base ? `${base}${p}` : p;
}
