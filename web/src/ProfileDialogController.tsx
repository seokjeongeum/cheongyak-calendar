import { forwardRef, memo, useCallback, useImperativeHandle, useRef, useState } from 'react'
import { ProfileDialog } from './ProfileDialog'
import type { LocalProfile, Notice } from './types'

export interface ProfileDialogHandle { open: (field?: keyof LocalProfile) => void; currentDraft: () => LocalProfile }

/** Opening a local editor must not reconcile the whole public calendar. */
export const ProfileDialogController = memo(forwardRef<ProfileDialogHandle, {
  profile: LocalProfile; onChange: (profile: LocalProfile) => void; today: string; notices: Notice[]
}>(function ProfileDialogController(props, ref) {
  const [state, setState] = useState<{ open: boolean; field?: keyof LocalProfile }>({ open: false })
  const draft = useRef(props.profile)
  if (!state.open) draft.current = props.profile
  const onDraft = useCallback((profile: LocalProfile) => { draft.current = profile }, [])
  const close = useCallback(() => setState((old) => ({ ...old, open: false })), [])
  useImperativeHandle(ref, () => ({ open: (field) => setState({ open: true, field }), currentDraft: () => draft.current }), [])
  return <ProfileDialog {...props} onDraft={onDraft} open={state.open} initialField={state.field} onClose={close} />
}))
