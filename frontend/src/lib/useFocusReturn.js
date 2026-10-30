import { useRef } from 'react'

// Dialogs opened from state (not from a Dialog.Trigger) lose their opener when they close, so keyboard focus
// would fall back to <body>. This remembers the element that had focus at the moment the dialog opened and
// restores it when Radix reports the dialog closed.
export function useFocusReturn(open) {
  const opener = useRef(null)
  const wasOpen = useRef(false)
  if (open && !wasOpen.current) opener.current = document.activeElement // read during render, before the dialog takes focus
  wasOpen.current = open
  return (e) => {
    const el = opener.current
    opener.current = null
    if (el && el.isConnected) { e.preventDefault(); el.focus() }
  }
}
