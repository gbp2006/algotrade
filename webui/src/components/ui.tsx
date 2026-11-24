import * as TabsPrimitive from '@radix-ui/react-tabs';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import {
  flexRender, getCoreRowModel, useReactTable, type ColumnDef,
} from '@tanstack/react-table';
import type { ReactNode } from 'react';

export function Card({ title, children, action, className = '' }: {
  title?: string; children: ReactNode; action?: ReactNode; className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {title && <h3 className="panel-title">{title}</h3>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Badge({ live }: { live: boolean }) {
  return <span className={live ? 'badge-live' : 'badge-test'}>{live ? 'LIVE' : 'TEST'}</span>;
}

export function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card min-w-[150px] flex-1">
      <div className="panel-title">{label}</div>
      <div className="num mt-1 text-xl font-semibold">{value}</div>
      {hint && <div className="mt-1 text-[11px] text-muted">{hint}</div>}
    </div>
  );
}

interface TabDef { id: string; label: string }

export function Tabs({ tabs, value, onChange, children }: {
  tabs: TabDef[]; value: string; onChange: (tab: string) => void; children: ReactNode;
}) {
  return (
    <TabsPrimitive.Root value={value} onValueChange={onChange} className="mt-4">
      <TabsPrimitive.List className="mb-3 flex flex-wrap gap-1 border-b border-line pb-2">
        {tabs.map((tab) => (
          <TabsPrimitive.Trigger
            key={tab.id}
            value={tab.id}
            className="rounded-md px-3 py-1.5 text-xs text-muted transition hover:bg-elevated hover:text-ink data-[state=active]:bg-accent data-[state=active]:text-white"
          >
            {tab.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      {children}
    </TabsPrimitive.Root>
  );
}

export function TabPanel({ value, children }: { value: string; children: ReactNode }) {
  return <TabsPrimitive.Content value={value} className="outline-none">{children}</TabsPrimitive.Content>;
}

export function DataTable<T>({ data, columns, empty = 'Данных пока нет' }: {
  data: T[]; columns: ColumnDef<T, unknown>[]; empty?: string;
}) {
  const table = useReactTable({
    data, columns, getCoreRowModel: getCoreRowModel(),
  });
  if (!data.length) return <div className="empty">{empty}</div>;
  return (
    <div className="max-h-[520px] overflow-auto rounded-lg border border-line">
      <table className="w-full min-w-[640px] border-collapse">
        <thead>{table.getHeaderGroups().map((group) => (
          <tr key={group.id}>{group.headers.map((header) => (
            <th key={header.id} className="th">{header.isPlaceholder
              ? null : flexRender(header.column.columnDef.header, header.getContext())}</th>
          ))}</tr>
        ))}</thead>
        <tbody>{table.getRowModel().rows.map((row) => (
          <tr key={row.id} className="hover:bg-elevated">{row.getVisibleCells().map((cell) => (
            <td key={cell.id} className="td">{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
          ))}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function ConfirmDialog({ open, title, message, onConfirm, onCancel }: {
  open: boolean; title: string; message: string;
  onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={(next) => { if (!next) onCancel(); }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-50 w-[min(420px,92vw)] -translate-x-1/2 -translate-y-1/2 rounded-card border border-line bg-surface p-6 shadow-2xl">
          <DialogPrimitive.Title className="text-base font-semibold">{title}</DialogPrimitive.Title>
          <DialogPrimitive.Description className="mt-2 text-sm text-muted">{message}</DialogPrimitive.Description>
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" className="btn" onClick={onCancel}>Отмена</button>
            <button type="button" className="btn-danger" onClick={onConfirm}>Подтвердить</button>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export function FormDialog({ title, message, onConfirm, onCancel, children }: {
  title: string; message?: string; onConfirm: () => void; onCancel: () => void;
  children: ReactNode;
}) {
  return (
    <DialogPrimitive.Root open onOpenChange={(next) => { if (!next) onCancel(); }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-50 w-[min(440px,92vw)] -translate-x-1/2 -translate-y-1/2 rounded-card border border-line bg-surface p-6 shadow-2xl">
          <DialogPrimitive.Title className="text-base font-semibold">{title}</DialogPrimitive.Title>
          {message && <DialogPrimitive.Description className="mt-1 text-xs text-muted">{message}</DialogPrimitive.Description>}
          <div className="mt-4 grid gap-3">{children}</div>
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" className="btn" onClick={onCancel}>Отмена</button>
            <button type="button" className="btn-primary" onClick={onConfirm}>Сохранить</button>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export function JsonDialog({ title, value, onClose }: {
  title: string; value: Record<string, unknown> | null; onClose: () => void;
}) {
  return (
    <DialogPrimitive.Root open={value !== null} onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-50 max-h-[80vh] w-[min(640px,92vw)] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-card border border-line bg-surface p-6 shadow-2xl">
          <DialogPrimitive.Title className="text-base font-semibold">{title}</DialogPrimitive.Title>
          <pre className="num mt-3 overflow-x-auto rounded-lg bg-elevated p-3 text-[11px] leading-relaxed">
            {JSON.stringify(value ?? {}, null, 2)}
          </pre>
          <div className="mt-4 flex justify-end">
            <button type="button" className="btn" onClick={onClose}>Закрыть</button>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export function Loading() {
  return <div className="grid gap-3 sm:grid-cols-3">{[0, 1, 2].map((n) => (
    <div key={n} className="skeleton h-20" />))}</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return <div className="rounded-lg border border-loss bg-surface p-3 text-xs text-loss">{message}</div>;
}
