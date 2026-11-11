import { useCallback } from "react";
import { useEpisodeLedger } from "@/hooks/useEpisodeLedger";
import { shotHierarchyCode } from "@/utils/shot-hierarchy";

/** Stable internal IDs never determine the director-facing episode position. */
export function useShotHierarchyCode() {
  const ledger = useEpisodeLedger();
  return useCallback((value: unknown) => shotHierarchyCode(value, ledger), [ledger]);
}
