"""A placeholder panel in the standard catalog: the objectives, switchable."""

from arkitekt import bsx

from newswitch.arkitekt_app import nsapp

nsapp.blok(
    "jonda",
    bsx("""
            <Card id="opentrons-controller" className="w-[380px] border-blue-200 shadow-md">
                <CardHeader>
                    <CardTitle text="Newswitch Handler" />
                    <CardDescription text="Bene don't look at this yet, this is just a placeholder" />
                </CardHeader>
                <CardContent className="grid gap-4">
                    <div className="flex items-center justify-between p-3 border rounded-md bg-slate-50">
                        <span className="text-sm font-medium text-slate-700" text="Deck Status" />
                        <span className="text-xs font-bold text-blue-700 bg-blue-100 border border-blue-200 px-2 py-1 rounded-full" text="Idle" />
                    </div>
                    <div className="grid grid-cols-2 gap-2 mt-2">
                        <foreach items="@self.ObjectiveState.mounted_lenses" let="#lens">
                            <Button
                                label="@lens.name"
                                onClick="@self.switch_objective(lens.slot)"
                            />
                        </foreach>
                    </div>
                </CardContent>
            </Card>
        """),
)
