// Painel de gestão de usuários — reusado em Configurações (aba Usuários e
// papéis) e Minha conta (Gestão de usuários). Só admins veem a lista de
// verdade; os demais papéis recebem uma explicação de para quem pedir.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import {
  createUser,
  deleteUser,
  getStoredUser,
  listUsers,
  patchUser,
  resetPassword,
} from "../api/client";
import type { Role, UserOut } from "../types";
import { ROLE_META } from "../utils";
import { FormField } from "./FormField";
import { Modal } from "./Modal";

const ROLE_OPTIONS: { value: Role; label: string }[] = [
  { value: "admin", label: "Admin — gerencia usuários e servidores" },
  { value: "operator", label: "Operador — edita servidores/config" },
  { value: "viewer", label: "Visualizador — somente leitura" },
];

const ROLE_TEXT: Record<Role, string> = {
  admin: "text-red-400 bg-status-crit/[.12] border-status-crit/30",
  operator: "text-amber-400 bg-status-warn/[.1] border-status-warn/[.28]",
  viewer: "text-[#8b93a7] bg-status-offline/[.12] border-status-offline/[.28]",
};

function RoleChip({ role }: { role: Role }) {
  return (
    <span
      className={`w-fit flex-none rounded border px-[9px] py-[3px] font-plex-sans text-[10px] font-semibold uppercase tracking-[0.05em] ${ROLE_TEXT[role]}`}
    >
      {ROLE_META[role].label}
    </span>
  );
}

function RoleSelect({ value, onChange }: { value: Role; onChange: (role: Role) => void }) {
  return (
    <label className="block font-plex-sans">
      <span className="text-[11px] font-medium uppercase tracking-wide text-[#8b93a7]">
        Papel
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as Role)}
        className="mt-1.5 w-full rounded-md border border-[#272c3a] bg-[#12151d] px-3 py-2 text-[13px] text-[#e2e6f0] outline-none focus:border-blue-500"
      >
        {ROLE_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function InlineCreateForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [done, setDone] = useState(false);

  const create = useMutation({
    mutationFn: () =>
      createUser({ username, password, display_name: displayName || null, role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setDone(true);
    },
  });

  return (
    <div className="flex flex-col gap-3 border-b border-[#232836] bg-[#171a24] px-4 py-3.5">
      <div className="grid grid-cols-2 gap-3">
        <FormField label="Usuário" value={username} onChange={setUsername} mono placeholder="ex: maria.l" />
        <FormField
          label="Nome de exibição (opcional)"
          value={displayName}
          onChange={setDisplayName}
          placeholder="ex: Maria Lima"
        />
        <FormField
          label="Senha inicial"
          type="password"
          mono
          value={password}
          onChange={setPassword}
          placeholder="mínimo 8 caracteres"
        />
        <RoleSelect value={role} onChange={setRole} />
      </div>
      <div className="flex items-center gap-2.5">
        <button
          type="button"
          onClick={() => create.mutate()}
          disabled={create.isPending || done || !username || password.length < 8}
          className="rounded-md bg-blue-500 px-[18px] py-2 font-plex-sans text-[12.5px] font-semibold text-white transition-colors hover:bg-blue-600 disabled:opacity-50"
        >
          {create.isPending ? "Criando…" : "Criar usuário"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded-md border border-[#272c3a] px-3.5 py-2 font-plex-sans text-[12.5px] font-medium text-[#8b93a7] hover:text-[#c6cddc]"
        >
          Cancelar
        </button>
        {done && (
          <span className="font-plex-sans text-xs font-medium text-status-ok">
            ✓ Usuário criado — deve trocar a senha no primeiro acesso
          </span>
        )}
        {create.isError && (
          <span className="font-plex-sans text-xs text-status-crit">
            Falha ao criar — verifique se o usuário já existe.
          </span>
        )}
      </div>
    </div>
  );
}

function DeleteUserModal({ user, onClose }: { user: UserOut; onClose: () => void }) {
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => deleteUser(user.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
  });

  return (
    <Modal
      title="Remover usuário"
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-4 py-2 font-plex-sans text-sm text-[#8b93a7] hover:text-[#c6cddc]"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-status-crit px-4 py-2 font-plex-sans text-sm font-semibold text-white transition hover:bg-red-600 disabled:opacity-60"
          >
            {remove.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
            Remover definitivamente
          </button>
        </>
      }
    >
      Isto remove <strong>{user.username}</strong> e encerra todas as sessões dele. Esta ação
      não pode ser desfeita.
      {remove.isError && (
        <p className="mt-3 text-xs text-status-crit">
          Falha ao remover — pode ser o último administrador ativo.
        </p>
      )}
    </Modal>
  );
}

function EditUserModal({ user, onClose }: { user: UserOut; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [role, setRole] = useState<Role>(user.role);
  const [isActive, setIsActive] = useState(user.is_active);
  const [showDelete, setShowDelete] = useState(false);
  const me = getStoredUser();

  const save = useMutation({
    mutationFn: () =>
      patchUser(user.id, { display_name: displayName || null, role, is_active: isActive }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
  });

  return (
    <>
      <Modal
        title={`Editar — ${user.username}`}
        onClose={onClose}
        footer={
          <div className="flex w-full items-center justify-between">
            <button
              type="button"
              onClick={() => setShowDelete(true)}
              disabled={user.username === me?.username}
              title={user.username === me?.username ? "Você não pode remover sua própria conta" : undefined}
              className="font-plex-sans text-xs font-medium text-status-crit hover:underline disabled:opacity-30 disabled:no-underline"
            >
              Remover usuário…
            </button>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={onClose}
                className="rounded-md px-4 py-2 font-plex-sans text-sm text-[#8b93a7] hover:text-[#c6cddc]"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => save.mutate()}
                disabled={save.isPending}
                className="inline-flex items-center gap-2 rounded-md bg-blue-500 px-4 py-2 font-plex-sans text-sm font-semibold text-white transition hover:bg-blue-600 disabled:opacity-60"
              >
                {save.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
                Salvar
              </button>
            </div>
          </div>
        }
      >
        <div className="space-y-4">
          <FormField label="Nome de exibição" value={displayName} onChange={setDisplayName} />
          <RoleSelect value={role} onChange={setRole} />
          <label className="flex items-center gap-2 font-plex-sans text-sm text-[#c6cddc]">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="h-4 w-4 accent-blue-500"
            />
            Usuário ativo (pode logar)
          </label>
          {save.isError && (
            <p className="text-xs text-status-crit">
              Falha ao salvar — pode ser o último administrador ativo.
            </p>
          )}
        </div>
      </Modal>
      {showDelete && <DeleteUserModal user={user} onClose={() => setShowDelete(false)} />}
    </>
  );
}

function ResetPasswordModal({ user, onClose }: { user: UserOut; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);

  const reset = useMutation({
    mutationFn: () => resetPassword(user.id, password),
    onSuccess: () => setDone(true),
  });

  return (
    <Modal
      title={`Redefinir senha — ${user.username}`}
      onClose={onClose}
      footer={
        done ? (
          <button
            type="button"
            onClick={onClose}
            className="rounded-md bg-blue-500 px-4 py-2 font-plex-sans text-sm font-semibold text-white hover:bg-blue-600"
          >
            Fechar
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md px-4 py-2 font-plex-sans text-sm text-[#8b93a7] hover:text-[#c6cddc]"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={() => reset.mutate()}
              disabled={reset.isPending || password.length < 8}
              className="inline-flex items-center gap-2 rounded-md bg-status-warn px-4 py-2 font-plex-sans text-sm font-semibold text-slate-950 transition hover:brightness-95 disabled:opacity-60"
            >
              {reset.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
              Redefinir
            </button>
          </>
        )
      }
    >
      {done ? (
        <p>
          Senha redefinida. Todas as sessões ativas de <strong>{user.username}</strong> foram
          encerradas — o próximo login usa a nova senha.
        </p>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-[#5b6274]">
            Isso encerra todas as sessões ativas de {user.username} imediatamente.
          </p>
          <FormField
            label="Nova senha"
            type="password"
            mono
            value={password}
            onChange={setPassword}
            hint="Mínimo de 8 caracteres."
          />
        </div>
      )}
    </Modal>
  );
}

export function UsersPanel() {
  const me = getStoredUser();
  const isAdmin = me?.role === "admin";

  const { data: users, isLoading } = useQuery<UserOut[]>({
    queryKey: ["users"],
    queryFn: listUsers,
    enabled: isAdmin,
  });

  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<UserOut | null>(null);
  const [resetting, setResetting] = useState<UserOut | null>(null);

  if (!isAdmin) {
    const meta = me ? ROLE_META[me.role] : null;
    return (
      <section className="flex flex-col items-center gap-2.5 rounded-lg border border-dashed border-[#272c3a] p-10 text-center">
        <span className="font-plex-sans text-[13px] font-medium text-[#8b93a7]">
          Gestão de usuários disponível apenas para administradores
        </span>
        <span className="max-w-[380px] font-plex-sans text-[11.5px] leading-[1.55] text-[#5b6274]">
          Seu papel atual é{" "}
          <span className={meta ? ROLE_TEXT[me!.role].split(" ")[0] : ""}>{meta?.label}</span>.
          Para criar ou editar usuários, peça a um administrador.
        </span>
      </section>
    );
  }

  return (
    <section className="overflow-hidden rounded-lg border border-[#272c3a] bg-[#1a1d27]">
      <div className="flex items-center gap-2 border-b border-[#232836] px-4 py-3">
        <span className="font-plex-sans text-[12.5px] font-semibold text-[#c6cddc]">
          Gestão de usuários
        </span>
        <span className="font-plex-mono text-[11px] text-[#5b6274]">
          {users?.length ?? "…"} usuários
        </span>
        <button
          type="button"
          onClick={() => setShowCreate((v) => !v)}
          className="ml-auto rounded-md bg-blue-500 px-3.5 py-1.5 font-plex-sans text-xs font-semibold text-white transition-colors hover:bg-blue-600"
        >
          {showCreate ? "Fechar" : "+ Novo usuário"}
        </button>
      </div>

      {showCreate && <InlineCreateForm onDone={() => setShowCreate(false)} />}

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-14 font-plex-sans text-sm text-[#5b6274]">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Carregando…
        </div>
      ) : (
        (users ?? []).map((user) => (
          <div
            key={user.id}
            className={`flex items-center gap-3 border-b border-[#1f2432] px-4 py-2.5 last:border-0 hover:bg-[#1e2230] ${
              user.is_active ? "" : "opacity-[.55]"
            }`}
          >
            <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full border border-[#2c3549] bg-[#1e2738] font-plex-sans text-[10px] font-semibold text-[#9fb3d9]">
              {(user.display_name ?? user.username).slice(0, 2).toUpperCase()}
            </span>
            <span className="flex w-[170px] min-w-0 flex-col leading-tight">
              <span className="truncate font-plex-sans text-[13px] font-medium text-[#c6cddc]">
                {user.display_name ?? user.username}
              </span>
              <span className="font-plex-mono text-[11px] text-[#5b6274]">{user.username}</span>
            </span>
            <RoleChip role={user.role} />
            <span className="w-[110px] font-plex-mono text-[11.5px] text-[#8b93a7]">
              {new Date(user.created_at).toLocaleDateString("pt-BR")}
            </span>
            <span className="flex items-center gap-1.5 font-plex-sans text-[11.5px] text-[#8b93a7]">
              <span className={`h-[7px] w-[7px] rounded-full ${user.is_active ? "bg-status-ok" : "bg-status-offline"}`} />
              {user.is_active ? "ativo" : "desativado"}
            </span>
            <span className="ml-auto flex flex-none gap-1.5">
              <button
                type="button"
                onClick={() => setEditing(user)}
                className="rounded-md border border-[#272c3a] px-2.5 py-1 font-plex-sans text-[11.5px] font-medium text-[#8b93a7] hover:border-blue-500 hover:text-[#c6cddc]"
              >
                Editar
              </button>
              <button
                type="button"
                onClick={() => setResetting(user)}
                className="rounded-md border border-[#272c3a] px-2.5 py-1 font-plex-sans text-[11.5px] font-medium text-[#8b93a7] hover:border-blue-500 hover:text-[#c6cddc]"
              >
                Resetar senha
              </button>
            </span>
          </div>
        ))
      )}

      <div className="px-4 py-2.5 font-plex-sans text-[11px] text-[#5b6274]">
        Papéis: <span className="text-red-400">Admin</span> gerencia usuários e servidores ·{" "}
        <span className="text-amber-400">Operador</span> edita servidores e configurações ·{" "}
        <span className="text-[#8b93a7]">Visualizador</span> somente leitura.
      </div>

      {editing && <EditUserModal user={editing} onClose={() => setEditing(null)} />}
      {resetting && <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} />}
    </section>
  );
}
