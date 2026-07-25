import { forwardRef } from "react";
import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  multiline?: false;
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  multiline: true;
}

type Props = InputProps | TextareaProps;

const inputCls =
  "bg-bg border border-border rounded-md px-4 font-body text-sm text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-muted-foreground hover:border-muted-foreground focus:border-primary focus:shadow-[0_0_0_2px_rgba(139,44,58,0.15)] disabled:opacity-50 disabled:cursor-not-allowed disabled:bg-surface-dim";

const Input = forwardRef<HTMLInputElement | HTMLTextAreaElement, Props>(
  function Input(props, ref) {
    const { className = "", multiline: _, ...rest } = props;

    if (props.multiline) {
      const taCls = `flex-1 min-w-0 resize-none ${inputCls} ${className}`.trim();
      return (
        <textarea
          className={taCls}
          ref={ref as React.Ref<HTMLTextAreaElement>}
          {...(rest as TextareaHTMLAttributes<HTMLTextAreaElement>)}
        />
      );
    }

    const inCls = `w-60 h-10 min-w-[120px] shrink-0 ${inputCls} ${className}`.trim();
    return (
      <input
        className={inCls}
        ref={ref as React.Ref<HTMLInputElement>}
        {...(rest as InputHTMLAttributes<HTMLInputElement>)}
      />
    );
  }
);

export default Input;
