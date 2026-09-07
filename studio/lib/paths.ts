/** The filesystem path behind a settings value: a sqlite DSN's file
 *  (`sqlite:////Users/x/a.db` → `/Users/x/a.db`), anything else as is.
 *  The Settings path picker opens here instead of at home (F15). */
export function pathFromValue(value: string): string {
  const m = /^sqlite:\/\/\/(.*)$/.exec(value.trim());
  return m ? "/" + m[1].replace(/^\/+/, "") : value;
}
