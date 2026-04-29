"use client";

import { useChat } from "@ai-sdk/react";
import { Bot, ChevronDown, MessageCircle, RefreshCw, Send, Square, X } from "lucide-react";
import { DefaultChatTransport, type UIMessage } from "ai";
import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

function messageText(message: UIMessage) {
  return message.parts
    .filter((part): part is Extract<UIMessage["parts"][number], { type: "text" }> => part.type === "text")
    .map((part) => part.text)
    .join("\n")
    .trim();
}

export function ChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: "/api/chat"
      }),
    []
  );

  const { clearError, error, messages, regenerate, sendMessage, status, stop } = useChat({
    transport
  });

  const isBusy = status === "submitted" || status === "streaming";
  const canSend = input.trim().length > 0 && !isBusy;

  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus();
    }
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
  }, [isOpen, messages, status]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const text = input.trim();
    if (!text || isBusy) {
      return;
    }

    clearError();
    setInput("");
    await sendMessage({ text });
  }

  if (!isOpen) {
    return (
      <button
        aria-label="Open AI assistant"
        className="fixed bottom-4 right-4 z-50 inline-flex h-14 w-14 items-center justify-center rounded-lg border border-slate-700 bg-slate-950 text-white shadow-2xl transition hover:bg-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2"
        title="Open AI assistant"
        type="button"
        onClick={() => setIsOpen(true)}
      >
        <MessageCircle aria-hidden="true" className="h-6 w-6" />
      </button>
    );
  }

  return (
    <aside
      aria-label="AI assistant"
      className="fixed bottom-4 right-4 z-50 flex h-[min(620px,calc(100vh-2rem))] w-[calc(100vw-2rem)] max-w-[390px] flex-col overflow-hidden rounded-lg border border-slate-300 bg-white shadow-2xl"
    >
      <header className="flex items-center justify-between gap-3 border-b border-slate-200 bg-slate-950 px-4 py-3 text-white">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-teal-600">
            <Bot aria-hidden="true" className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">AI assistant</h2>
            <p className="truncate text-xs text-slate-300">{isBusy ? "Thinking" : "Ready"}</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            aria-label="Minimize assistant"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-200 transition hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-teal-400"
            title="Minimize assistant"
            type="button"
            onClick={() => setIsOpen(false)}
          >
            <ChevronDown aria-hidden="true" className="h-5 w-5" />
          </button>
          <button
            aria-label="Close assistant"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-200 transition hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-teal-400"
            title="Close assistant"
            type="button"
            onClick={() => setIsOpen(false)}
          >
            <X aria-hidden="true" className="h-5 w-5" />
          </button>
        </div>
      </header>

      <div className="sidebar-scroll flex-1 overflow-y-auto bg-slate-50 px-4 py-4" aria-live="polite">
        {messages.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm leading-6 text-slate-600">
            <p className="font-semibold text-slate-950">Hi. What can I help you find?</p>
          </div>
        ) : (
          <div className="space-y-3">
            {messages.map((message) => {
              const text = messageText(message);
              if (!text) {
                return null;
              }

              const isUser = message.role === "user";
              return (
                <div key={message.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[85%] rounded-lg px-3 py-2 text-sm leading-6 shadow-sm ${
                      isUser
                        ? "bg-slate-950 text-white"
                        : "border border-slate-200 bg-white text-slate-700"
                    }`}
                  >
                    <p className="whitespace-pre-wrap break-words">{text}</p>
                  </div>
                </div>
              );
            })}
            {isBusy ? (
              <div className="flex justify-start">
                <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-500 shadow-sm">
                  Thinking...
                </div>
              </div>
            ) : null}
          </div>
        )}

        {error ? (
          <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            <p>{error.message || "The assistant could not respond."}</p>
            <button
              className="mt-2 inline-flex h-8 items-center gap-2 rounded-lg border border-red-200 bg-white px-3 text-xs font-semibold text-red-700 transition hover:border-red-300 hover:bg-red-100"
              type="button"
              onClick={() => {
                clearError();
                void regenerate();
              }}
            >
              <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" />
              Retry
            </button>
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      <form className="border-t border-slate-200 bg-white p-3" onSubmit={handleSubmit}>
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            aria-label="Message"
            className="max-h-32 min-h-11 flex-1 resize-none rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm leading-5 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
            placeholder="Ask a question..."
            rows={1}
            value={input}
            onChange={(event) => setInput(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          {isBusy ? (
            <button
              aria-label="Stop response"
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-slate-300 bg-white text-slate-700 transition hover:border-amber-400 hover:text-amber-700 focus:outline-none focus:ring-2 focus:ring-amber-300"
              title="Stop response"
              type="button"
              onClick={() => {
                void stop();
              }}
            >
              <Square aria-hidden="true" className="h-5 w-5" />
            </button>
          ) : (
            <button
              aria-label="Send message"
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-white transition hover:bg-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:cursor-not-allowed disabled:bg-slate-300"
              disabled={!canSend}
              title="Send message"
              type="submit"
            >
              <Send aria-hidden="true" className="h-5 w-5" />
            </button>
          )}
        </div>
      </form>
    </aside>
  );
}
