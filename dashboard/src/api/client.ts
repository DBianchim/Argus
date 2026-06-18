// Client HTTP do dashboard: anexa o token de sessão e trata 401 globalmente.

import type { LoginOut } from "../types";

const TOKEN_KEY = "argus_token";
const USER_KEY = "argus_user";

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): { username: string; display_name: string | null } | null {
  const raw = sessionStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function storeSession(login: LoginOut): void {
  sessionStorage.setItem(TOKEN_KEY, login.token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(login.user));
}

export function clearSession(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken() ?? ""}`,
      ...init?.headers,
    },
  });

  if (response.status === 401) {
    // Sessão expirada/revogada — volta para a entrada
    clearSession();
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new Error("Sessão expirada");
  }
  if (!response.ok) {
    throw new Error(`Erro ${response.status}`);
  }
  // 204 (ex.: DELETE) e corpos vazios não têm JSON para parsear.
  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export async function login(username: string, password: string): Promise<LoginOut> {
  const response = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (response.status === 401) {
    throw new Error("Credenciais inválidas");
  }
  if (!response.ok) {
    throw new Error("Falha ao conectar com o servidor");
  }
  return response.json() as Promise<LoginOut>;
}

export async function logout(): Promise<void> {
  try {
    await api("/api/v1/auth/logout", { method: "POST" });
  } finally {
    clearSession();
  }
}
