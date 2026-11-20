#!/usr/bin/env bash
# cct-endpoint.sh — how CCT renders and checks an endpoint URL. Shared
# by the routing supervisor (cooldown-supervisor.sh) and the LLM catalog
# (llm-catalog.sh); moved here for #479 (#400 FR-7) so there is one
# origin grammar, the one routing-result.sh's RR_ORIGIN_RE validates.
#
# bash 3.2 compatible; no dependencies.

# rt_sanitize_origin <url> -> scheme://host[:port], or EMPTY.
#
# The ORIGIN only: scheme, host, optional port. Credentials, path,
# query and fragment are dropped, so a base URL carrying a token or a
# tenant path can never become durable evidence. Anything that is not a
# well-formed absolute URL yields EMPTY — the caller records that as
# unknown rather than substituting something weaker.
rt_sanitize_origin() {
  local u="$1" scheme rest authority
  [[ -n "$u" ]] || return 0
  # HTTP(S) ONLY — the registry defines base_url as an absolute http(s)
  # URL, but base_url_env validates only the VARIABLE NAME, so the
  # RESOLVED value is unchecked. Without this, `ftp://` and even
  # `javascript://` resolved from the environment were recorded as
  # usable origins.
  [[ "$u" =~ ^([Hh][Tt][Tt][Pp][Ss]?)://(.*)$ ]] || return 0
  scheme=$(printf '%s' "${BASH_REMATCH[1]}" | tr 'A-Z' 'a-z')
  rest="${BASH_REMATCH[2]}"
  rest="${rest%%#*}"          # fragment
  rest="${rest%%\?*}"         # query
  authority="${rest%%/*}"     # path
  authority="${authority##*@}"  # user:password@
  [[ -n "$authority" ]] || return 0
  # host[:port], or a bracketed IPv6 literal with an optional port
  if [[ "$authority" =~ ^\[[0-9A-Fa-f:.]+\](:[0-9]+)?$ ]] \
     || [[ "$authority" =~ ^[A-Za-z0-9._~-]+(:[0-9]+)?$ ]]; then
    # Hosts are case-insensitive; normalize so one endpoint cannot be
    # recorded as two, which would defeat the distinction this exists
    # to make. Ports are digits and unaffected.
    printf '%s://%s' "$scheme" "$(printf '%s' "$authority" | tr 'A-Z' 'a-z')"
  fi
}

# ce_url_violation <url> -> why the URL is refused as an endpoint base
# URL, or EMPTY when it is acceptable: absolute http(s), a usable host,
# and no userinfo, query or fragment (a base URL is configuration, never
# a place for a credential).
ce_url_violation() {
  local u="$1" rest authority
  if [[ ! "$u" =~ ^[Hh][Tt][Tt][Pp][Ss]?://(.*)$ ]]; then
    printf 'must be an absolute http(s) URL'
    return 0
  fi
  rest="${BASH_REMATCH[1]}"
  if [[ "$rest" == *"#"* ]]; then printf 'must not carry a fragment'; return 0; fi
  if [[ "$rest" == *"?"* ]]; then printf 'must not carry a query'; return 0; fi
  authority="${rest%%/*}"
  if [[ "$authority" == *"@"* ]]; then printf 'must not carry userinfo'; return 0; fi
  if [[ -z "$(rt_sanitize_origin "$u")" ]]; then printf 'has no usable host'; return 0; fi
  return 0
}
