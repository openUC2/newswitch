import { acquisition } from "./acquisition";
import { users, audit } from "./admin";
import { auth } from "./auth";
import { common, language, navigation, roles, taskStatus } from "./common";
import { microscope } from "./microscope";

export const de = {
  common,
  language,
  auth,
  navigation,
  roles,
  taskStatus,
  users,
  audit,
  acquisition,
  microscope,
} as const;
