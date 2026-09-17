import { useState } from "react";
import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  type LanguagePreference,
  readLanguagePreference,
  setLanguagePreference,
} from "@/i18n";
import { cn } from "@/lib/utils";

export function LanguageMenu({ className }: { className?: string }) {
  const { t } = useTranslation();
  const [preference, setPreference] = useState<LanguagePreference>(
    readLanguagePreference,
  );

  const changeLanguage = (value: string) => {
    const next = value as LanguagePreference;
    setPreference(next);
    void setLanguagePreference(next);
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("language.menu")}
          className={cn("h-8 w-8 bg-background/70 backdrop-blur", className)}
        >
          <Languages className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>{t("language.label")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preference}
          onValueChange={changeLanguage}
        >
          <DropdownMenuRadioItem value="system">
            {t("language.system")}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="de">
            {t("language.german")}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="en">
            {t("language.english")}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
