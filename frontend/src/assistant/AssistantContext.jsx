import { createContext, useContext } from 'react'

// Shell owns the single assistant conversation and live voice session; the chat panel and the Voice Assistant page both read them from here.
export const AssistantContext = createContext(null)
export const useAssistantContext = () => useContext(AssistantContext)
