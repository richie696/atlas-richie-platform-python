import { useId, useState } from "react";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import { DialogFrame } from "../../../src/shared/ui/DialogFrame";
import { ActionButton } from "../../../src/shared/ui/ActionButton";
import { FormGrid } from "../../../src/shared/ui/FormGrid";
import { TextField } from "../../../src/shared/ui/TextField";

/** Tests frame lifecycle with real controls; the pending command is deliberately local. */
export function DialogProbe() {
  const formId = useId();
  const [isOpen, setOpen] = useState(false);
  const [isBusy, setBusy] = useState(false);
  const [value, setValue] = useState("");
  const [submits, setSubmits] = useState(0);
  const [long, setLong] = useState(false);
  return (
    <AstryxProvider>
      <button data-action="open" onClick={() => setOpen(true)}>
        Open workflow
      </button>
      <button data-action="length" onClick={() => setLong((current) => !current)}>
        Long content
      </button>
      <output data-dialog-state>{JSON.stringify({ isOpen, isBusy, value, submits })}</output>
      <DialogFrame
        isOpen={isOpen}
        onOpenChange={setOpen}
        isBusy={isBusy}
        title={
          long ? "ルール設定を確認して保存する前に変更内容を詳細に確認してください" : "Workflow"
        }
        subtitle={
          long
            ? "説明文が複数行に折り返されても、見出しと操作ボタンは表示されたまま、フォーム本文のみがスクロールします。"
            : "A controlled form task"
        }
        actions={
          <>
            <ActionButton data-action="cancel" disabled={isBusy} onClick={() => setOpen(false)}>
              Cancel
            </ActionButton>
            <ActionButton data-action="submit" type="submit" form={formId} disabled={isBusy}>
              Submit
            </ActionButton>
            {isBusy && (
              <ActionButton
                data-action="finish"
                onClick={() => {
                  setBusy(false);
                  setOpen(false);
                }}
              >
                Confirm outcome
              </ActionButton>
            )}
          </>
        }
      >
        <form
          id={formId}
          onSubmit={(event) => {
            event.preventDefault();
            if (isBusy) return;
            setSubmits((current) => current + 1);
            setBusy(true);
          }}
        >
          <FormGrid columns={1}>
            <TextField label="Resource" value={value} onChange={setValue} disabled={isBusy} />
          </FormGrid>
          {long &&
            Array.from({ length: 30 }, (_, index) => (
              <p key={index}>
                詳細項目 {index + 1} — 長い内容は本文内でスクロールし、操作を隠さないこと。
              </p>
            ))}
        </form>
      </DialogFrame>
    </AstryxProvider>
  );
}
