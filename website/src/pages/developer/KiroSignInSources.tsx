import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Info, Loader2 } from 'lucide-react'
import { api, type KasLoginSourceAccount, type KasLoginSources } from '../../api/client'
import { accountProviderLabel } from '../../components/kasProviderLabel'
import { clearCachedModels } from '../../providers/adapters/acp'
import ErrorNotice from '../../components/ErrorNotice'
import { Btn } from '../../components/ui'
import { i18nT } from '../../i18n/t'

/** Cache key of `GET /api/kas-login/sources`: which stored sign-in sessions run as. */
export const SOURCES_QUERY_KEY = ['kas-login-sources'] as const
// Same key the sign-in flow reads status under (KasLoginGate.QUERY_KEY).
const STATUS_QUERY_KEY = ['kas-login'] as const
// How often to ask again while the gateway is still reading kiro-cli's account name.
const NAME_POLL_MS = 2000

/**
 * Which stored sign-in sessions run as. A read of its own, apart from the sign-in
 * status the card paints from, so a slow answer never holds the card back. Asks
 * again only while the gateway reports the kiro-cli account name as still being read.
 */
export function useKiroSignInSources() {
  return useQuery({
    queryKey: SOURCES_QUERY_KEY,
    queryFn: api.kasLoginSources,
    refetchInterval: query => (query.state.data?.name_pending ? NAME_POLL_MS : false),
  })
}

/**
 * Remove the sign-in stored in this app (the card's Sign out, and "Use the Kiro
 * CLI account"). One mutation for both, so each leaves the same state behind.
 */
export function useKiroSignOut(identity: string, onSignedOut: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.kasLoginLogout(identity),
    onSuccess: () => {
      onSignedOut()
      void queryClient.invalidateQueries({ queryKey: STATUS_QUERY_KEY })
      void queryClient.invalidateQueries({ queryKey: SOURCES_QUERY_KEY })
      // The signed-out account's model list goes with it: the gateway forgot its
      // catalog on this sign-out, and `['available-models']` would otherwise stay
      // fresh (global `staleTime: Infinity`) until a session spawns.
      clearCachedModels()
      void queryClient.resetQueries({ queryKey: ['available-models'] })
    },
  })
}

export type SourcesNotice = 'using_kiro_cli' | 'two_accounts' | 'maybe_two_accounts'

/** What the card has to say about the two stored sign-ins, or `null` for nothing. */
export function sourcesNotice(sources: KasLoginSources | undefined): SourcesNotice | null {
  if (!sources) return null
  if (sources.active === 'kiro_cli') return 'using_kiro_cli'
  if (sources.active !== 'kiro_crew') return null
  // A kiro-cli sign-in that has expired is not an account anything could run as.
  if (sources.kiro_cli.stored !== true || !sources.kiro_cli.usable) return null
  if (sources.same_account === false) return 'two_accounts'
  if (sources.same_account === null) return 'maybe_two_accounts'
  return null
}

/** An account as the card names it: its e-mail, else its kind and portal, else a plain "could not read". */
function accountName(account: KasLoginSourceAccount, pending: boolean): string {
  if (account.email) return account.email
  const label = accountProviderLabel(
    account.account_type,
    account.portal_host ? `https://${account.portal_host}` : undefined,
  )
  if (label) return label
  return pending
    ? i18nT('pages.developer.kiroSignInCard.account_name_checking')
    : i18nT('pages.developer.kiroSignInCard.account_name_unreadable')
}

/**
 * Says which account Kiro Agent runs as when kiro-cli is signed in too:
 * - nothing stored here: sessions use the kiro-cli sign-in, named;
 * - both stored for different accounts (or not provably the same): names both and
 *   offers to remove the one stored here, so sessions go back to kiro-cli's.
 * Removing asks once, in place, and is undone by signing in here again.
 */
export function KiroSignInSourcesNotice({
  sources,
  identity,
  onRemoved,
}: {
  sources: KasLoginSources | undefined
  /** The stored sign-in's slot (`KasLoginStatus.identity`), which the removal names. */
  identity: string
  onRemoved: () => void
}) {
  const kind = sourcesNotice(sources)
  const [confirming, setConfirming] = useState(false)
  const remove = useKiroSignOut(identity, onRemoved)
  if (!sources || !kind) return null
  const cli = accountName(sources.kiro_cli, sources.name_pending)
  if (kind === 'using_kiro_cli') {
    return (
      <div
        className="mb-3 flex items-start gap-3"
        role="status"
        data-testid="kiro-sign-in-sources"
        data-notice={kind}
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-ok/15 text-ok-text" aria-hidden="true">
          <Info className="lucide-inline" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-text-strong">
            {i18nT('pages.developer.kiroSignInCard.using_kiro_cli_title')}
          </p>
          <p className="mt-0.5 text-[13px] leading-relaxed text-muted">
            {i18nT('pages.developer.kiroSignInCard.using_kiro_cli_body', { account: cli })}
          </p>
        </div>
      </div>
    )
  }
  const here = accountName(sources.kiro_crew, false)
  return (
    <div className="mb-4" role="status" data-testid="kiro-sign-in-sources" data-notice={kind}>
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-warn/15 text-warn-text" aria-hidden="true">
          <AlertTriangle className="lucide-inline" />
        </div>
        <div className="min-w-0 flex-1">
          {kind === 'two_accounts' ? (
            <p className="text-sm font-medium text-text-strong">
              {i18nT('pages.developer.kiroSignInCard.two_accounts_title')}
            </p>
          ) : null}
          <p className="mt-0.5 text-[13px] leading-relaxed text-muted">
            {kind === 'two_accounts'
              ? i18nT('pages.developer.kiroSignInCard.two_accounts_body', { here, cli })
              : i18nT('pages.developer.kiroSignInCard.maybe_two_accounts_body', { here, cli })}
          </p>
          {sources.can_use_kiro_cli && !confirming ? (
            <Btn
              type="button"
              className="mt-2"
              onClick={() => setConfirming(true)}
              data-testid="kiro-sign-in-use-kiro-cli"
            >
              {i18nT('pages.developer.kiroSignInCard.use_kiro_cli_account')}
            </Btn>
          ) : null}
          {sources.can_use_kiro_cli && confirming ? (
            <div className="mt-2" role="group" aria-label={i18nT('pages.developer.kiroSignInCard.use_kiro_cli_account')}>
              <p className="text-[13px] leading-relaxed text-text" data-testid="kiro-sign-in-use-kiro-cli-explain">
                {i18nT('pages.developer.kiroSignInCard.use_kiro_cli_explain')}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Btn
                  type="button"
                  danger
                  disabled={remove.isPending}
                  onClick={() => remove.mutate()}
                  data-testid="kiro-sign-in-remove"
                >
                  {remove.isPending ? <Loader2 className="lucide-inline animate-spin" aria-hidden="true" /> : null}
                  {i18nT('pages.developer.kiroSignInCard.remove_this_sign_in')}
                </Btn>
                {/* Focus lands on the choice that changes nothing. */}
                <Btn
                  type="button"
                  autoFocus
                  disabled={remove.isPending}
                  onClick={() => setConfirming(false)}
                  data-testid="kiro-sign-in-keep"
                >
                  {i18nT('pages.developer.kiroSignInCard.keep_it')}
                </Btn>
              </div>
            </div>
          ) : null}
        </div>
      </div>
      <ErrorNotice
        className="mt-3"
        askAgent
        title={i18nT('pages.developer.kiroSignInCard.could_not_sign_out')}
        message={remove.error?.message || null}
        testId="kiro-sign-in-remove-error"
      />
    </div>
  )
}
