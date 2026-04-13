import type { InputHTMLAttributes, ReactNode } from "react";

type BaseProps = {
  label: ReactNode;
  hint?: ReactNode;
  children?: ReactNode;
};

// Generic labelled field wrapper used around both controlled inputs and
// custom controls (checkbox chip rows, multi-selects, etc).
export function Field({ label, hint, children }: BaseProps) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint ? <small className="muted">{hint}</small> : null}
    </div>
  );
}

type InputFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: ReactNode;
  hint?: ReactNode;
};

export function InputField({ label, hint, ...rest }: InputFieldProps) {
  return (
    <Field label={label} hint={hint}>
      <input {...rest} />
    </Field>
  );
}
