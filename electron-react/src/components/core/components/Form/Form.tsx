import React, { ReactNode } from 'react';
import { UseFormMethods, FormProvider, SubmitHandler } from "react-hook-form";

export default function Form<T>(props: {
  methods: UseFormMethods<T>,
  onSubmit: SubmitHandler<T>,
  children: ReactNode,
}) {
  const { methods, onSubmit, ...rest } = props;
  const { handleSubmit } = methods;

  return (
    <FormProvider {...methods}>
      <form
        onSubmit={handleSubmit(onSubmit)}
        {...rest}
      />
    </FormProvider>
  );
}
