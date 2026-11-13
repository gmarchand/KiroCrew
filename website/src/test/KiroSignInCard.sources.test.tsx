import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from './helpers'
import { KiroSignInCard } from '../pages/developer/KiroSignInCard'
import { sourcesNotice } from '../pages/developer/KiroSignInSources'
import { api, type KasLoginSources, type KasLoginStatus } from '../api/client'

vi.mock('../api/client', async importOriginal => {
  const mod = await importOriginal<typeof import('../api/client')>()
  return {
    ...mod,
    api: {
      ...mod.api,
      kasLoginStatus: vi.fn(),
      kasLoginSources: vi.fn(),
      kasLoginLogout: vi.fn().mockResolvedValue({ ok: true }),
      kasLoginBeginDevice: vi.fn(),
      kasLoginPoll: vi.fn().mockResolvedValue({ status: 'pending' }),
      kasLoginBeginLoopback: vi.fn(),
      kasLoginCancel: vi.fn().mockResolvedValue({ ok: true }),
    },
  }
})

const kasLoginStatus = vi.mocked(api.kasLoginStatus)
const kasLoginSources = vi.mocked(api.kasLoginSources)
const kasLoginLogout = vi.mocked(api.kasLoginLogout)

const SIGNED_OUT: KasLoginStatus = {
  authenticated: false,
  provider: '',
  identity: '',
  transport: 'device',
  expires_at: null,
  expired: false,
  has_refresh_token: false,
  refresh_rejected: false,
  usable: false,
}

const SIGNED_IN: KasLoginStatus = {
  authenticated: true,
  provider: 'BuilderId',
  identity: 'builder_id',
  transport: 'device',
  expires_at: '2099-01-01T00:00:00Z',
  expired: false,
  has_refresh_token: true,
  refresh_rejected: false,
  usable: true,
}

const NONE: KasLoginSources = {
  active: 'none',
  kiro_crew: { stored: false },
  kiro_cli: { stored: false, usable: false },
  name_pending: false,
  same_account: null,
  can_use_kiro_cli: false,
}

const ONLY_KIRO_CLI: KasLoginSources = {
  ...NONE,
  active: 'kiro_cli',
  kiro_cli: {
    stored: true,
    usable: true,
    account_type: 'IamIdentityCenter',
    portal_host: 'example.awsapps.com',
    email: 'person@example.com',
  },
}

const TWO_ACCOUNTS: KasLoginSources = {
  active: 'kiro_crew',
  kiro_crew: { stored: true, account_type: 'BuilderId' },
  kiro_cli: { stored: true, usable: true, account_type: 'IamIdentityCenter', portal_host: 'example.awsapps.com' },
  name_pending: false,
  same_account: false,
  can_use_kiro_cli: true,
}

describe('KiroSignInCard: which account Kiro Agent runs as', () => {
  beforeEach(() => {
    kasLoginStatus.mockReset()
    kasLoginSources.mockReset()
    kasLoginLogout.mockClear()
  })

  it('says nothing extra when kiro-cli is not signed in', async () => {
    kasLoginStatus.mockResolvedValue(SIGNED_OUT)
    kasLoginSources.mockResolvedValue(NONE)
    renderWithProviders(<KiroSignInCard />)
    await screen.findByTestId('kas-login-embedded')
    await waitFor(() => expect(kasLoginSources).toHaveBeenCalled())
    expect(screen.queryByTestId('kiro-sign-in-sources')).toBeNull()
  })

  it('nothing stored here and kiro-cli signed in: says sessions use the Kiro CLI sign-in and names the account', async () => {
    kasLoginStatus.mockResolvedValue(SIGNED_OUT)
    kasLoginSources.mockResolvedValue(ONLY_KIRO_CLI)
    renderWithProviders(<KiroSignInCard />)
    const notice = await screen.findByTestId('kiro-sign-in-sources')
    expect(notice).toHaveAttribute('data-notice', 'using_kiro_cli')
    expect(notice).toHaveTextContent('Using your Kiro CLI sign-in')
    expect(notice).toHaveTextContent(
      'Kiro Agent runs as the account Kiro CLI is signed in to: person@example.com. You don\'t need to sign in here.',
    )
    // Nothing of this app's is stored, so there is nothing to remove.
    expect(screen.queryByTestId('kiro-sign-in-use-kiro-cli')).toBeNull()
    // The chooser is still there for a person who wants another account.
    expect(screen.getByTestId('kas-login-embedded')).toBeInTheDocument()
  })

  it('names the account by its kind and portal when no e-mail was read', async () => {
    kasLoginStatus.mockResolvedValue(SIGNED_OUT)
    kasLoginSources.mockResolvedValue({
      ...ONLY_KIRO_CLI,
      kiro_cli: { stored: true, usable: true, account_type: 'IamIdentityCenter', portal_host: 'example.awsapps.com' },
    })
    renderWithProviders(<KiroSignInCard />)
    const notice = await screen.findByTestId('kiro-sign-in-sources')
    expect(notice).toHaveTextContent('signed in to: IAM Identity Center · example.awsapps.com.')
  })

  it('shows the state before the name arrives, then the name, and says so when it cannot be read', async () => {
    kasLoginStatus.mockResolvedValue(SIGNED_OUT)
    kasLoginSources.mockResolvedValue({ ...ONLY_KIRO_CLI, kiro_cli: { stored: true, usable: true }, name_pending: true })
    const { queryClient } = renderWithProviders(<KiroSignInCard />)
    const notice = await screen.findByTestId('kiro-sign-in-sources')
    expect(notice).toHaveTextContent('signed in to: an account whose name is still being read.')
    act(() => queryClient.setQueryData(['kas-login-sources'], ONLY_KIRO_CLI))
    await waitFor(() => expect(notice).toHaveTextContent('signed in to: person@example.com.'))
    act(() =>
      queryClient.setQueryData(['kas-login-sources'], { ...ONLY_KIRO_CLI, kiro_cli: { stored: true, usable: true } }),
    )
    await waitFor(() =>
      expect(screen.getByTestId('kiro-sign-in-sources')).toHaveTextContent(
        'signed in to: an account whose name Kiro Crew could not read.',
      ),
    )
  })

  it('two different accounts: names both and offers the Kiro CLI one, removing only after a confirm', async () => {
    kasLoginStatus.mockResolvedValue(SIGNED_IN)
    kasLoginSources.mockResolvedValue(TWO_ACCOUNTS)
    renderWithProviders(<KiroSignInCard />)
    const notice = await screen.findByTestId('kiro-sign-in-sources')
    expect(notice).toHaveAttribute('data-notice', 'two_accounts')
    expect(notice).toHaveTextContent('Two different accounts are signed in')
    expect(notice).toHaveTextContent(
      'Kiro Agent runs as the account you signed in with here: Builder ID. Kiro CLI is signed in to another account: IAM Identity Center · example.awsapps.com. Kiro Agent is not using it.',
    )
    fireEvent.click(screen.getByTestId('kiro-sign-in-use-kiro-cli'))
    // One press removes nothing: it explains, and focus is on the choice that keeps things as they are.
    expect(kasLoginLogout).not.toHaveBeenCalled()
    expect(screen.getByTestId('kiro-sign-in-use-kiro-cli-explain')).toHaveTextContent(
      'This removes the sign-in stored here. Kiro Agent then runs as the Kiro CLI account. To undo it, sign in here again.',
    )
    expect(screen.getByTestId('kiro-sign-in-keep')).toHaveFocus()
    fireEvent.click(screen.getByTestId('kiro-sign-in-keep'))
    expect(screen.queryByTestId('kiro-sign-in-remove')).toBeNull()
    expect(kasLoginLogout).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('kiro-sign-in-use-kiro-cli'))
    kasLoginStatus.mockResolvedValue(SIGNED_OUT)
    kasLoginSources.mockResolvedValue({ ...ONLY_KIRO_CLI, kiro_cli: TWO_ACCOUNTS.kiro_cli })
    fireEvent.click(screen.getByTestId('kiro-sign-in-remove'))
    await waitFor(() => expect(kasLoginLogout).toHaveBeenCalledWith('builder_id'))
    // The card then reads both again and says sessions run on the Kiro CLI sign-in.
    await waitFor(() =>
      expect(screen.getByTestId('kiro-sign-in-sources')).toHaveAttribute('data-notice', 'using_kiro_cli'),
    )
    expect(screen.getByTestId('kiro-sign-in-takes-effect')).toBeInTheDocument()
  })

  it('cannot tell whether they are one account: says so without calling them different', async () => {
    kasLoginStatus.mockResolvedValue(SIGNED_IN)
    kasLoginSources.mockResolvedValue({
      ...TWO_ACCOUNTS,
      kiro_cli: { stored: true, usable: true, account_type: 'BuilderId' },
      same_account: null,
    })
    renderWithProviders(<KiroSignInCard />)
    const notice = await screen.findByTestId('kiro-sign-in-sources')
    expect(notice).toHaveAttribute('data-notice', 'maybe_two_accounts')
    expect(notice).not.toHaveTextContent('Two different accounts')
    expect(notice).toHaveTextContent(
      'Kiro CLI is also signed in: Builder ID. Kiro Crew cannot tell whether they are the same account.',
    )
    expect(screen.getByTestId('kiro-sign-in-use-kiro-cli')).toBeInTheDocument()
  })

  it('offers no button where removing would not put sessions on the Kiro CLI sign-in', async () => {
    kasLoginStatus.mockResolvedValue(SIGNED_IN)
    kasLoginSources.mockResolvedValue({ ...TWO_ACCOUNTS, can_use_kiro_cli: false })
    renderWithProviders(<KiroSignInCard />)
    await screen.findByTestId('kiro-sign-in-sources')
    expect(screen.queryByTestId('kiro-sign-in-use-kiro-cli')).toBeNull()
  })

  it('compact: two different accounts open the fold a signed-in card would keep closed', async () => {
    kasLoginStatus.mockResolvedValue(SIGNED_IN)
    kasLoginSources.mockResolvedValue(TWO_ACCOUNTS)
    renderWithProviders(<KiroSignInCard compact />)
    const card = screen.getByTestId('kiro-sign-in-card') as HTMLDetailsElement
    await waitFor(() => expect(card.open).toBe(true))
    expect(screen.getByTestId('kiro-sign-in-sources')).toBeInTheDocument()
  })

  it('a failed read of the sources leaves the card as it was', async () => {
    kasLoginStatus.mockResolvedValue(SIGNED_IN)
    kasLoginSources.mockRejectedValue(new Error('boom'))
    renderWithProviders(<KiroSignInCard />)
    await screen.findByTestId('kiro-sign-in-summary')
    expect(screen.queryByTestId('kiro-sign-in-sources')).toBeNull()
  })
})

describe('sourcesNotice', () => {
  it.each([
    [undefined, null],
    [NONE, null],
    [{ ...NONE, active: 'unknown' as const }, null],
    [ONLY_KIRO_CLI, 'using_kiro_cli'],
    [TWO_ACCOUNTS, 'two_accounts'],
    [{ ...TWO_ACCOUNTS, same_account: null }, 'maybe_two_accounts'],
    // One account in both places is not something to warn about.
    [{ ...TWO_ACCOUNTS, same_account: true }, null],
    // An expired kiro-cli sign-in is not an account anything could run as.
    [{ ...TWO_ACCOUNTS, kiro_cli: { stored: true, usable: false } }, null],
    // A store that could not be read is unknown, never "two accounts".
    [{ ...TWO_ACCOUNTS, kiro_cli: { stored: null, usable: false } }, null],
  ])('%#', (sources, expected) => {
    expect(sourcesNotice(sources as KasLoginSources | undefined)).toBe(expected)
  })
})
