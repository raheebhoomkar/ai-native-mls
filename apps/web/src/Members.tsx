import { type FormEvent, useState } from "react";

import {
  api,
  type CurrentOrganisation,
  type Me,
  ROLE_LABELS,
  type Role,
  tokenLink,
  useAction,
  useList,
} from "./api";
import { OneTimeLink } from "./OneTimeLink";

type Member = {
  user_id: string;
  email: string;
  full_name: string;
  role: Role;
};
type Invitation = { id: string; email: string; role: Role; expires_at: string };

export function Members({
  me,
  organisation,
}: {
  me: Me;
  organisation: CurrentOrganisation;
}) {
  const canManage = organisation.my_permissions.includes("member:manage");
  const members = useList<Member>(
    "/organisations/current/members",
    organisation.id,
  );
  const change = useAction();
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);

  function setRole(member: Member, role: Role) {
    void change.run(async () => {
      await api(`/organisations/current/members/${member.user_id}`, {
        method: "PATCH",
        body: { role },
      });
      members.reload();
    });
  }

  function remove(member: Member) {
    void change.run(async () => {
      await api(`/organisations/current/members/${member.user_id}`, {
        method: "DELETE",
      });
      setConfirmRemove(null);
      members.reload();
    });
  }

  return (
    <section aria-labelledby="members-heading">
      <h2 id="members-heading">Members of {organisation.name}</h2>
      {members.loading && <p className="loading">Loading…</p>}
      {members.error && <p role="alert">{members.error}</p>}
      {change.error && <p role="alert">{change.error}</p>}
      {!members.loading && !members.error && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Email</th>
                <th scope="col">Role</th>
                {canManage && <th scope="col">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {members.items.map((member) => {
                const isSelf = member.user_id === me.user.id;
                return (
                  <tr key={member.user_id}>
                    <td>
                      {member.full_name}
                      {isSelf && " (you)"}
                    </td>
                    <td>{member.email}</td>
                    <td>
                      {canManage && !isSelf ? (
                        <select
                          aria-label={`Role of ${member.full_name}`}
                          value={member.role}
                          disabled={change.busy}
                          onChange={(e) =>
                            setRole(member, e.target.value as Role)
                          }
                        >
                          {organisation.assignable_roles.map((role) => (
                            <option key={role} value={role}>
                              {ROLE_LABELS[role]}
                            </option>
                          ))}
                        </select>
                      ) : (
                        ROLE_LABELS[member.role]
                      )}
                    </td>
                    {canManage && (
                      <td>
                        {isSelf ? (
                          "—"
                        ) : confirmRemove === member.user_id ? (
                          <>
                            <button
                              type="button"
                              disabled={change.busy}
                              onClick={() => remove(member)}
                            >
                              Confirm removal
                            </button>{" "}
                            <button
                              type="button"
                              onClick={() => setConfirmRemove(null)}
                            >
                              Cancel
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setConfirmRemove(member.user_id)}
                          >
                            Remove
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {members.next && (
        <button type="button" onClick={() => void members.loadMore()}>
          Load more
        </button>
      )}
      {canManage && <Invitations organisation={organisation} />}
    </section>
  );
}

function Invitations({ organisation }: { organisation: CurrentOrganisation }) {
  const pending = useList<Invitation>(
    "/organisations/current/invitations",
    organisation.id,
  );
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("agent");
  const [link, setLink] = useState<{ email: string; url: string } | null>(null);
  const invite = useAction();
  const revoke = useAction();

  function submit(event: FormEvent) {
    event.preventDefault();
    void invite.run(async () => {
      const created = await api<{ email: string; token: string }>(
        "/organisations/current/invitations",
        { method: "POST", body: { email, role } },
      );
      setLink({
        email: created.email,
        url: tokenLink("accept-invite", created.token),
      });
      setEmail("");
      pending.reload();
    });
  }

  return (
    <>
      <form onSubmit={submit} aria-labelledby="invite-form-heading">
        <h3 id="invite-form-heading">Invite a person</h3>
        <label htmlFor="invite-email">Email</label>
        <input
          id="invite-email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label htmlFor="invite-role">Role</label>
        <select
          id="invite-role"
          value={role}
          onChange={(e) => setRole(e.target.value as Role)}
        >
          {organisation.assignable_roles.map((option) => (
            <option key={option} value={option}>
              {ROLE_LABELS[option]}
            </option>
          ))}
        </select>
        {invite.error && <p role="alert">{invite.error}</p>}
        <button type="submit" disabled={invite.busy}>
          {invite.busy ? "Creating…" : "Create invitation link"}
        </button>
      </form>
      {link && (
        <OneTimeLink
          label={`Invitation for ${link.email} created.`}
          link={link.url}
        />
      )}

      <h3>Pending invitations</h3>
      {pending.error && <p role="alert">{pending.error}</p>}
      {revoke.error && <p role="alert">{revoke.error}</p>}
      {!pending.loading && pending.items.length === 0 && !pending.error && (
        <p>No pending invitations.</p>
      )}
      <ul>
        {pending.items.map((invitation) => (
          <li key={invitation.id}>
            {invitation.email} — {ROLE_LABELS[invitation.role]}, expires{" "}
            {new Date(invitation.expires_at).toLocaleDateString()}{" "}
            <button
              type="button"
              disabled={revoke.busy}
              aria-label={`Revoke invitation for ${invitation.email}`}
              onClick={() =>
                void revoke.run(async () => {
                  await api(
                    `/organisations/current/invitations/${invitation.id}`,
                    { method: "DELETE" },
                  );
                  pending.reload();
                })
              }
            >
              Revoke
            </button>
          </li>
        ))}
      </ul>
      {pending.next && (
        <button type="button" onClick={() => void pending.loadMore()}>
          Load more
        </button>
      )}
    </>
  );
}
