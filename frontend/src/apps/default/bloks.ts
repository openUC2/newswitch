// Generated from /schemas/bloks. Do not edit.

/** The bloks the backend declares, by key. */
export const bloks = {
  jonda: {
    args: null,
    catalog: null,
    components: [
      {
        children: [
          {
            children: [
              {
                children: null,
                component: 'CardTitle',
                id: 'opentrons-controller/CardHeader[0]/CardTitle[0]',
                props: [
                  {
                    agentCall: null,
                    declaresValue: null,
                    dynamicValue: null,
                    key: 'text',
                    staticValue: 'Newswitch Handler',
                    utilCall: null,
                  },
                ],
              },
              {
                children: null,
                component: 'CardDescription',
                id: 'opentrons-controller/CardHeader[0]/CardDescription[0]',
                props: [
                  {
                    agentCall: null,
                    declaresValue: null,
                    dynamicValue: null,
                    key: 'text',
                    staticValue:
                      "Bene don't look at this yet, this is just a placeholder",
                    utilCall: null,
                  },
                ],
              },
            ],
            component: 'CardHeader',
            id: 'opentrons-controller/CardHeader[0]',
            props: null,
          },
          {
            children: [
              {
                children: [
                  {
                    children: null,
                    component: 'span',
                    id: 'opentrons-controller/CardContent[0]/div[0]/span[0]',
                    props: [
                      {
                        agentCall: null,
                        declaresValue: null,
                        dynamicValue: null,
                        key: 'className',
                        staticValue: 'text-sm font-medium text-slate-700',
                        utilCall: null,
                      },
                      {
                        agentCall: null,
                        declaresValue: null,
                        dynamicValue: null,
                        key: 'text',
                        staticValue: 'Deck Status',
                        utilCall: null,
                      },
                    ],
                  },
                  {
                    children: null,
                    component: 'span',
                    id: 'opentrons-controller/CardContent[0]/div[0]/span[1]',
                    props: [
                      {
                        agentCall: null,
                        declaresValue: null,
                        dynamicValue: null,
                        key: 'className',
                        staticValue:
                          'text-xs font-bold text-blue-700 bg-blue-100 border border-blue-200 px-2 py-1 rounded-full',
                        utilCall: null,
                      },
                      {
                        agentCall: null,
                        declaresValue: null,
                        dynamicValue: null,
                        key: 'text',
                        staticValue: 'Idle',
                        utilCall: null,
                      },
                    ],
                  },
                ],
                component: 'div',
                id: 'opentrons-controller/CardContent[0]/div[0]',
                props: [
                  {
                    agentCall: null,
                    declaresValue: null,
                    dynamicValue: null,
                    key: 'className',
                    staticValue:
                      'flex items-center justify-between p-3 border rounded-md bg-slate-50',
                    utilCall: null,
                  },
                ],
              },
              {
                children: [
                  {
                    children: [
                      {
                        children: null,
                        component: 'Button',
                        id: 'opentrons-controller/CardContent[0]/div[1]/foreach[0]/Button[0]',
                        props: [
                          {
                            agentCall: null,
                            declaresValue: null,
                            dynamicValue: { literal: null, path: 'lens.name' },
                            key: 'label',
                            staticValue: null,
                            utilCall: null,
                          },
                          {
                            agentCall: {
                              arguments: [
                                {
                                  agentCall: null,
                                  key: '0',
                                  utilCall: null,
                                  valueDict: null,
                                  valueList: null,
                                  valueLiteral: null,
                                  valuePath: 'lens.slot',
                                },
                              ],
                              dependency: 'self',
                              operation: 'switch_objective',
                            },
                            declaresValue: null,
                            dynamicValue: null,
                            key: 'onClick',
                            staticValue: null,
                            utilCall: null,
                          },
                        ],
                      },
                    ],
                    component: 'foreach',
                    id: 'opentrons-controller/CardContent[0]/div[1]/foreach[0]',
                    props: [
                      {
                        agentCall: null,
                        declaresValue: null,
                        dynamicValue: {
                          literal: null,
                          path: 'self.ObjectiveState.mounted_lenses',
                        },
                        key: 'items',
                        staticValue: null,
                        utilCall: null,
                      },
                      {
                        agentCall: null,
                        declaresValue: 'lens',
                        dynamicValue: null,
                        key: 'let',
                        staticValue: 'lens',
                        utilCall: null,
                      },
                    ],
                  },
                ],
                component: 'div',
                id: 'opentrons-controller/CardContent[0]/div[1]',
                props: [
                  {
                    agentCall: null,
                    declaresValue: null,
                    dynamicValue: null,
                    key: 'className',
                    staticValue: 'grid grid-cols-2 gap-2 mt-2',
                    utilCall: null,
                  },
                ],
              },
            ],
            component: 'CardContent',
            id: 'opentrons-controller/CardContent[0]',
            props: [
              {
                agentCall: null,
                declaresValue: null,
                dynamicValue: null,
                key: 'className',
                staticValue: 'grid gap-4',
                utilCall: null,
              },
            ],
          },
        ],
        component: 'Card',
        id: 'opentrons-controller',
        props: [
          {
            agentCall: null,
            declaresValue: null,
            dynamicValue: null,
            key: 'className',
            staticValue: 'w-[380px] border-blue-200 shadow-md',
            utilCall: null,
          },
        ],
      },
    ],
    context: 'HTML',
    default: false,
    demoState: {
      self: {
        ObjectiveState: {
          magnification: 0,
          mounted_lenses: [],
          name: '',
          slot: 0,
        },
      },
    },
    dependencies: [
      {
        actionDependencies: [
          {
            allowInactive: true,
            demand: {
              app: null,
              argMatches: [
                {
                  at: 0,
                  children: null,
                  descriptors: null,
                  dimension: null,
                  identifier: null,
                  key: 'slot',
                  kind: 'INT',
                  nullable: false,
                },
              ],
              forceArgLength: null,
              forceReturnLength: null,
              hash: null,
              idempotent: null,
              key: 'switch_objective',
              name: null,
              protocols: null,
              pure: null,
              returnMatches: null,
              stateful: null,
              version: null,
            },
            description: 'Switch to a specific objective slot.',
            key: 'switch_objective',
            optional: false,
          },
        ],
        app: null,
        autoResolvable: false,
        description: null,
        key: 'self',
        maxViableInstances: null,
        minViableInstances: null,
        mutuallyExclusiveKeys: null,
        name: null,
        optional: false,
        preferedInstances: null,
        stateDependencies: [
          {
            allowInactive: true,
            demand: {
              app: null,
              hash: null,
              key: 'ObjectiveState',
              matches: [
                {
                  at: 0,
                  children: null,
                  descriptors: null,
                  dimension: null,
                  identifier: null,
                  key: 'slot',
                  kind: 'INT',
                  nullable: false,
                },
                {
                  at: 1,
                  children: null,
                  descriptors: null,
                  dimension: null,
                  identifier: null,
                  key: 'magnification',
                  kind: 'FLOAT',
                  nullable: false,
                },
                {
                  at: 2,
                  children: null,
                  descriptors: null,
                  dimension: null,
                  identifier: null,
                  key: 'name',
                  kind: 'STRING',
                  nullable: false,
                },
                {
                  at: 3,
                  children: [
                    {
                      at: 0,
                      children: [
                        {
                          at: 0,
                          children: null,
                          descriptors: null,
                          dimension: null,
                          identifier: null,
                          key: 'slot',
                          kind: 'INT',
                          nullable: false,
                        },
                        {
                          at: 1,
                          children: null,
                          descriptors: null,
                          dimension: null,
                          identifier: null,
                          key: 'name',
                          kind: 'STRING',
                          nullable: false,
                        },
                        {
                          at: 2,
                          children: null,
                          descriptors: null,
                          dimension: null,
                          identifier: null,
                          key: 'magnification',
                          kind: 'FLOAT',
                          nullable: false,
                        },
                        {
                          at: 3,
                          children: null,
                          descriptors: null,
                          dimension: null,
                          identifier: null,
                          key: 'numerical_aperture',
                          kind: 'FLOAT',
                          nullable: false,
                        },
                        {
                          at: 4,
                          children: null,
                          descriptors: null,
                          dimension: null,
                          identifier: null,
                          key: 'working_distance',
                          kind: 'FLOAT',
                          nullable: false,
                        },
                        {
                          at: 5,
                          children: null,
                          descriptors: null,
                          dimension: null,
                          identifier: null,
                          key: 'binning_factor',
                          kind: 'INT',
                          nullable: false,
                        },
                      ],
                      descriptors: null,
                      dimension: null,
                      identifier: '@newswitch/objective_lens',
                      key: '...',
                      kind: 'MODEL',
                      nullable: false,
                    },
                  ],
                  descriptors: null,
                  dimension: null,
                  identifier: null,
                  key: 'mounted_lenses',
                  kind: 'LIST',
                  nullable: false,
                },
              ],
              protocols: null,
            },
            description: null,
            key: 'ObjectiveState',
            optional: false,
          },
        ],
        version: null,
      },
    ],
    description: null,
    forModel: null,
    forNode: null,
    key: 'jonda',
    source: null,
  },
  standard: {
    args: null,
    catalog: 'newswitch',
    components: [
      {
        children: [
          {
            children: [
              {
                children: null,
                component: 'SettingsPanel',
                id: 'Resizable/ResizablePanel[0]/SettingsPanel[0]',
                props: [
                  {
                    agentCall: null,
                    declaresValue: null,
                    dynamicValue: null,
                    key: 'className',
                    staticValue: 'h-full',
                    utilCall: null,
                  },
                ],
              },
            ],
            component: 'ResizablePanel',
            id: 'Resizable/ResizablePanel[0]',
            props: [
              {
                agentCall: null,
                declaresValue: null,
                dynamicValue: null,
                key: 'defaultSize',
                staticValue: '15',
                utilCall: null,
              },
              {
                agentCall: null,
                declaresValue: null,
                dynamicValue: null,
                key: 'minSize',
                staticValue: '10',
                utilCall: null,
              },
              {
                agentCall: null,
                declaresValue: null,
                dynamicValue: null,
                key: 'maxSize',
                staticValue: '30',
                utilCall: null,
              },
            ],
          },
          {
            children: null,
            component: 'ResizableHandle',
            id: 'Resizable/ResizableHandle[0]',
            props: [
              {
                agentCall: null,
                declaresValue: null,
                dynamicValue: null,
                key: 'withHandle',
                staticValue: 'true',
                utilCall: null,
              },
            ],
          },
          {
            children: [
              {
                children: [
                  {
                    children: [
                      {
                        children: [
                          {
                            children: null,
                            component: 'FrameLightPathLayer',
                            id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/StageScene[0]/FrameLightPathLayer[0]',
                            props: null,
                          },
                          {
                            children: null,
                            component: 'StageAxis',
                            id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/StageScene[0]/StageAxis[0]',
                            props: null,
                          },
                          {
                            children: null,
                            component: 'FramesLayer',
                            id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/StageScene[0]/FramesLayer[0]',
                            props: null,
                          },
                          {
                            children: null,
                            component: 'StagePlane',
                            id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/StageScene[0]/StagePlane[0]',
                            props: null,
                          },
                          {
                            children: null,
                            component: 'LivesLayer',
                            id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/StageScene[0]/LivesLayer[0]',
                            props: null,
                          },
                          {
                            children: null,
                            component: 'LightPathLayer',
                            id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/StageScene[0]/LightPathLayer[0]',
                            props: null,
                          },
                          {
                            children: null,
                            component: 'ImagesLayer',
                            id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/StageScene[0]/ImagesLayer[0]',
                            props: null,
                          },
                          {
                            children: null,
                            component: 'StagePositioner',
                            id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/StageScene[0]/StagePositioner[0]',
                            props: null,
                          },
                          {
                            children: null,
                            component: 'RectangleDrawer',
                            id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/StageScene[0]/RectangleDrawer[0]',
                            props: null,
                          },
                        ],
                        component: 'StageScene',
                        id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/StageScene[0]',
                        props: null,
                      },
                      {
                        children: null,
                        component: 'ScanRegionPanel',
                        id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/ScanRegionPanel[0]',
                        props: null,
                      },
                      {
                        children: null,
                        component: 'ImageMetadataPanel',
                        id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/ImageMetadataPanel[0]',
                        props: null,
                      },
                      {
                        children: null,
                        component: 'KubeStatePanel',
                        id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/KubeStatePanel[0]',
                        props: null,
                      },
                      {
                        children: null,
                        component: 'FramePanel',
                        id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/FramePanel[0]',
                        props: null,
                      },
                      {
                        children: null,
                        component: 'SceneOverlay',
                        id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/SceneOverlay[0]',
                        props: null,
                      },
                      {
                        children: null,
                        component: 'DebugOverlay',
                        id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]/DebugOverlay[0]',
                        props: null,
                      },
                    ],
                    component: 'StageView',
                    id: 'Resizable/ResizablePanel[1]/div[0]/StageView[0]',
                    props: [
                      {
                        agentCall: null,
                        declaresValue: null,
                        dynamicValue: null,
                        key: 'className',
                        staticValue: 'flex-1',
                        utilCall: null,
                      },
                    ],
                  },
                ],
                component: 'div',
                id: 'Resizable/ResizablePanel[1]/div[0]',
                props: [
                  {
                    agentCall: null,
                    declaresValue: null,
                    dynamicValue: null,
                    key: 'className',
                    staticValue:
                      'flex h-full flex-col overflow-hidden bg-muted/30',
                    utilCall: null,
                  },
                ],
              },
            ],
            component: 'ResizablePanel',
            id: 'Resizable/ResizablePanel[1]',
            props: [
              {
                agentCall: null,
                declaresValue: null,
                dynamicValue: null,
                key: 'defaultSize',
                staticValue: '55',
                utilCall: null,
              },
            ],
          },
          {
            children: null,
            component: 'ResizableHandle',
            id: 'Resizable/ResizableHandle[1]',
            props: [
              {
                agentCall: null,
                declaresValue: null,
                dynamicValue: null,
                key: 'withHandle',
                staticValue: 'true',
                utilCall: null,
              },
            ],
          },
          {
            children: [
              {
                children: [
                  {
                    children: [
                      {
                        children: null,
                        component: 'StageControl',
                        id: 'Resizable/ResizablePanel[2]/ScrollArea[0]/div[0]/StageControl[0]',
                        props: null,
                      },
                      {
                        children: null,
                        component: 'MultidimensionalAcquisitionControl',
                        id: 'Resizable/ResizablePanel[2]/ScrollArea[0]/div[0]/MultidimensionalAcquisitionControl[0]',
                        props: null,
                      },
                      {
                        children: null,
                        component: 'CalibrateLightPath',
                        id: 'Resizable/ResizablePanel[2]/ScrollArea[0]/div[0]/CalibrateLightPath[0]',
                        props: null,
                      },
                      {
                        children: null,
                        component: 'BloksPanel',
                        id: 'Resizable/ResizablePanel[2]/ScrollArea[0]/div[0]/BloksPanel[0]',
                        props: null,
                      },
                    ],
                    component: 'div',
                    id: 'Resizable/ResizablePanel[2]/ScrollArea[0]/div[0]',
                    props: [
                      {
                        agentCall: null,
                        declaresValue: null,
                        dynamicValue: null,
                        key: 'className',
                        staticValue: 'flex flex-col gap-4 p-4',
                        utilCall: null,
                      },
                    ],
                  },
                ],
                component: 'ScrollArea',
                id: 'Resizable/ResizablePanel[2]/ScrollArea[0]',
                props: [
                  {
                    agentCall: null,
                    declaresValue: null,
                    dynamicValue: null,
                    key: 'className',
                    staticValue: 'h-full',
                    utilCall: null,
                  },
                ],
              },
            ],
            component: 'ResizablePanel',
            id: 'Resizable/ResizablePanel[2]',
            props: [
              {
                agentCall: null,
                declaresValue: null,
                dynamicValue: null,
                key: 'defaultSize',
                staticValue: '30',
                utilCall: null,
              },
              {
                agentCall: null,
                declaresValue: null,
                dynamicValue: null,
                key: 'minSize',
                staticValue: '15',
                utilCall: null,
              },
              {
                agentCall: null,
                declaresValue: null,
                dynamicValue: null,
                key: 'maxSize',
                staticValue: '40',
                utilCall: null,
              },
            ],
          },
        ],
        component: 'Resizable',
        id: 'Resizable',
        props: [
          {
            agentCall: null,
            declaresValue: null,
            dynamicValue: null,
            key: 'direction',
            staticValue: 'row',
            utilCall: null,
          },
          {
            agentCall: null,
            declaresValue: null,
            dynamicValue: null,
            key: 'className',
            staticValue: 'h-full w-full',
            utilCall: null,
          },
        ],
      },
    ],
    context: 'HTML',
    default: true,
    demoState: {},
    dependencies: [],
    description: 'The default newswitch microscope UI.',
    forModel: null,
    forNode: null,
    key: 'standard',
    source: null,
  },
} as const;

export type BlokKey = 'jonda' | 'standard';
