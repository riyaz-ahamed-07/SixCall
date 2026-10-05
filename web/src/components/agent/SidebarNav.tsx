"use client";

import { useState, type CSSProperties, type ReactNode } from "react";
import GlideMenu from "@/components/primitives/GlideMenu";

const SIDEBAR_MOTION = {
  expandedWidth: 224,
  collapsedWidth: 52,
  duration: 280,
  copyDuration: 180,
  copyOffset: 8,
  easing: "cubic-bezier(0.16, 1, 0.3, 1)",
};

export type ChatListItem = {
  id: string;
  title: string;
  subtitle?: string;
  hasDoc?: boolean;
};

function RailButton({
  icon,
  label,
  active = false,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      data-row
      type="button"
      onClick={onClick}
      className={`sidebar-row relative z-10 mx-2 flex h-8 items-center rounded-[8px] px-2 text-left transition-[width,background-color,color,transform] duration-150 active:scale-[0.98] ${
        active ? "bg-hover-2 group-hover/glide:bg-transparent" : ""
      }`}
    >
      <span
        className={`flex size-5 shrink-0 items-center justify-center ${active ? "text-ink" : "text-ink-2"}`}
      >
        {icon}
      </span>
      <span
        className={`sidebar-copy ml-1.5 min-w-0 flex-1 truncate text-[14px] font-medium ${active ? "text-ink" : "text-ink-2"}`}
      >
        {label}
      </span>
    </button>
  );
}

export default function SidebarNav({
  chats,
  activeChatId,
  userEmail,
  uploadDisabled = false,
  onNewChat,
  onPickChat,
  onDeleteChat,
  onUploadClick,
  onLogout,
}: {
  chats: ChatListItem[];
  activeChatId?: string | null;
  userEmail?: string;
  uploadDisabled?: boolean;
  onNewChat?: () => void;
  onPickChat?: (chatId: string) => void;
  onDeleteChat?: (chatId: string) => void;
  onUploadClick?: () => void;
  onLogout?: () => void;
}) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      data-sidebar-collapsed={collapsed}
      aria-label="Workspace navigation"
      className="relative flex h-full shrink-0 overflow-hidden border-r border-line bg-canvas transition-[width]"
      style={
        {
          width: collapsed
            ? SIDEBAR_MOTION.collapsedWidth
            : SIDEBAR_MOTION.expandedWidth,
          transitionDuration: `${SIDEBAR_MOTION.duration}ms`,
          transitionTimingFunction: SIDEBAR_MOTION.easing,
          "--sidebar-copy-duration": `${SIDEBAR_MOTION.copyDuration}ms`,
          "--sidebar-copy-offset": `${SIDEBAR_MOTION.copyOffset}px`,
          "--sidebar-easing": SIDEBAR_MOTION.easing,
        } as CSSProperties
      }
    >
      <div className="flex min-h-0 w-[224px] shrink-0 flex-col py-2">
        <div className="relative mb-2.5 h-10 shrink-0">
          <div className="sidebar-workspace-control absolute left-2 top-1 flex h-8 w-[164px] items-center rounded-[8px] px-2">
            <span className="sidebar-logo flex size-5 shrink-0 items-center justify-center rounded-[6px] bg-accent text-[10px] font-bold text-white shadow-btn">
              6
            </span>
            <span className="sidebar-copy ml-1.5 min-w-0 flex-1 truncate text-[14px] font-semibold tracking-[-0.02em] text-ink">
              SixCall
            </span>
          </div>
          <button
            type="button"
            aria-label="Collapse sidebar"
            aria-hidden={collapsed}
            tabIndex={collapsed ? -1 : 0}
            onClick={() => setCollapsed(true)}
            className="sidebar-collapse-control absolute right-2 top-1 flex size-8 items-center justify-center rounded-[8px] text-ink-3 transition-[opacity,background-color,color] duration-150 hover:bg-hover-2 hover:text-ink"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
            >
              <path d="M4 6h10M4 12h16M4 18h10M15 8l-4 4 4 4" />
            </svg>
          </button>
          <button
            type="button"
            aria-label="Expand sidebar"
            aria-hidden={!collapsed}
            tabIndex={collapsed ? 0 : -1}
            onClick={() => setCollapsed(false)}
            className="sidebar-expand-control absolute left-2 top-0.5 flex size-9 items-center justify-center rounded-[8px] text-ink-3 transition-[opacity,background-color,color] duration-150 hover:bg-hover-2 hover:text-ink"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              className="rotate-180"
            >
              <path d="M4 6h10M4 12h16M4 18h10M15 8l-4 4 4 4" />
            </svg>
          </button>
        </div>

        <GlideMenu
          rowSelector="[data-row]"
          highlightClassName="sidebar-glide-highlight rounded-[7px] bg-hover-2"
          className="flex flex-col gap-px"
        >
          <RailButton
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
              >
                <path d="M12 5v14M5 12h14" />
              </svg>
            }
            label="New chat"
            onClick={onNewChat}
          />
          <RailButton
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
              >
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <path d="M14 2v6h6" />
              </svg>
            }
            label={uploadDisabled ? "Uploading…" : "Upload PDF"}
            onClick={uploadDisabled ? undefined : onUploadClick}
          />
        </GlideMenu>

        <div className="mt-3 min-h-0 flex-1 overflow-y-auto">
          <div className="sidebar-copy mx-2 mb-1 flex h-8 items-center gap-1.5 px-2 text-[12.5px] font-medium text-ink-3">
            Chats
          </div>
          <GlideMenu
            rowSelector="[data-row]"
            highlightClassName="sidebar-glide-highlight rounded-[7px] bg-hover-2"
            className="flex flex-col gap-px"
          >
            {chats.map((chat) => {
              const active = chat.id === activeChatId;
              return (
                <div
                  key={chat.id}
                  data-row
                  className={`sidebar-row group/chat relative z-10 mx-2 flex min-h-8 items-stretch rounded-[8px] transition-[width,background-color,color] duration-150 ${
                    active ? "bg-hover-2 group-hover/glide:bg-transparent" : ""
                  }`}
                >
                  <button
                    type="button"
                    title={chat.title}
                    onClick={() => onPickChat?.(chat.id)}
                    className="flex min-w-0 flex-1 flex-col justify-center rounded-[8px] px-2 py-1.5 text-left transition-transform duration-150 active:scale-[0.98]"
                  >
                    <span
                      className={`sidebar-copy min-w-0 w-full truncate text-[13.5px] font-medium ${active ? "text-ink" : "text-ink-2"}`}
                    >
                      {chat.title}
                    </span>
                    {chat.subtitle ? (
                      <span className="sidebar-copy mt-0.5 min-w-0 w-full truncate text-[11px] text-ink-3">
                        {chat.subtitle}
                      </span>
                    ) : null}
                  </button>
                  {onDeleteChat ? (
                    <button
                      type="button"
                      aria-label={`Delete ${chat.title}`}
                      title="Delete chat"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteChat(chat.id);
                      }}
                      className="sidebar-copy my-1 mr-1 flex size-7 shrink-0 items-center justify-center self-center rounded-[6px] text-ink-3 opacity-0 transition hover:bg-hover-2 hover:text-ink group-hover/chat:opacity-100 focus-visible:opacity-100"
                    >
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.8"
                      >
                        <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
                      </svg>
                    </button>
                  ) : null}
                </div>
              );
            })}
            {chats.length === 0 && (
              <div className="sidebar-copy mx-2 px-2 py-2 text-[12.5px] text-ink-3">
                No chats yet
              </div>
            )}
          </GlideMenu>
        </div>

        <div className="sidebar-copy mx-2 mt-3 w-[208px] border-t border-line pt-3">
          {userEmail ? (
            <p
              className="mb-2 truncate px-1 text-[11.5px] text-ink-3"
              title={userEmail}
            >
              {userEmail}
            </p>
          ) : null}
          <div className="rounded-control border border-line bg-surface px-2.5 py-2 text-[11.5px] leading-relaxed text-ink-2 shadow-hairline">
            <span className="font-medium text-ink">4 tools</span>
            <span className="text-ink-3"> · </span>
            6-call budget
          </div>
          {onLogout ? (
            <button
              type="button"
              onClick={onLogout}
              className="mt-2 w-full rounded-[8px] px-2.5 py-1.5 text-left text-[12px] font-medium text-ink-2 transition hover:bg-hover-2 hover:text-ink"
            >
              Sign out
            </button>
          ) : null}
        </div>
      </div>
    </aside>
  );
}
