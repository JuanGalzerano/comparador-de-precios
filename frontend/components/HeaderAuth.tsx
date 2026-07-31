import Link from "next/link";
import { getCurrentUser } from "@/lib/session";
import { UserMenu } from "./UserMenu";

/** Bloque de sesion del header. Server Component async: resuelve
 * `GET /auth/me` server-side (via `getCurrentUser`, cacheado por request) y
 * decide entre "Ingresar" o el dropdown de cuenta logueada. */
export async function HeaderAuth() {
  const user = await getCurrentUser();

  if (!user) {
    return (
      <Link href="/ingresar" className="btn btn-secondary" style={{ whiteSpace: "nowrap" }}>
        Ingresar
      </Link>
    );
  }

  const label = user.display_name ?? user.email.split("@")[0];
  return <UserMenu label={label} />;
}
