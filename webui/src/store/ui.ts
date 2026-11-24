import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Mode, Section } from '../lib/types';

interface UiState {
  section: Section;
  tab: string;
  mode: Mode;
  accountId: string;
  theme: 'dark' | 'light';
  density: 'comfortable' | 'compact';
  setSection: (section: Section) => void;
  setTab: (tab: string) => void;
  setMode: (mode: Mode) => void;
  setAccount: (accountId: string) => void;
  toggleTheme: () => void;
  toggleDensity: () => void;
}

const applyDocument = (theme: 'dark' | 'light', density: 'comfortable' | 'compact'): void => {
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.density = density;
};

export const useUi = create<UiState>()(persist((set, get) => ({
  section: 'portfolio',
  tab: '',
  mode: 'ALL',
  accountId: '',
  theme: 'dark',
  density: 'comfortable',
  setSection: (section) => set({ section, tab: '' }),
  setTab: (tab) => set({ tab }),
  setMode: (mode) => set({ mode }),
  setAccount: (accountId) => set({ accountId }),
  toggleTheme: () => {
    const theme = get().theme === 'dark' ? 'light' : 'dark';
    set({ theme });
    applyDocument(theme, get().density);
  },
  toggleDensity: () => {
    const density = get().density === 'compact' ? 'comfortable' : 'compact';
    set({ density });
    applyDocument(get().theme, density);
  },
}), {
  name: 'algo.ui.v1',
  partialize: (state) => ({
    section: state.section, tab: state.tab, mode: state.mode,
    accountId: state.accountId, theme: state.theme, density: state.density,
  }),
  onRehydrateStorage: () => (state) => {
    if (state) applyDocument(state.theme, state.density);
  },
}));
