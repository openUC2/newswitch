import { createContext, useContext, useEffect, type ReactNode } from "react";

/** Sets what a page puts on the left of the bottom bar (its view tabs, say). */
export const BottomBarSlotContext = createContext<
  (content: ReactNode | null) => void
>(() => undefined);

/** Put `content` on the left of the bottom bar while the calling page is shown. */
export function useBottomBarSlot(content: ReactNode | null) {
  const setSlot = useContext(BottomBarSlotContext);
  useEffect(() => {
    setSlot(content);
    return () => setSlot(null);
  }, [content, setSlot]);
}
