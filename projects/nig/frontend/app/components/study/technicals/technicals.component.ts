import { Component, Injector, Input } from "@angular/core";
import { DataService } from "@app/services/data.service";
import { BasePaginationComponent } from "@rapydo/components/base.pagination.component";
import { TechnicalMetadata } from "@app/types";
import { Subject } from "rxjs";

@Component({
  selector: "nig-technicals",
  templateUrl: "./technicals.component.html",
})
export class TechnicalsComponent extends BasePaginationComponent<TechnicalMetadata> {
  @Input() studyUUID;
  @Input() studyType;
  @Input() readonly;

  private platformKits: { [platform: string]: string[] } = {};

  constructor(protected injector: Injector, private dataService: DataService) {
    super(injector);
  }

  get isGenome(): boolean {
    return this.studyType === "genome";
  }

  ngOnInit() {
    this.init(
      "Technical Metadata",
      `/api/study/${this.studyUUID}/technicals`,
      "Technicals"
    );
    this.set_resource_endpoint("/api/technical");
    this.initPaging(20, false);
    this.list();

    this.dataService.getTechnicalOptions().subscribe((options) => {
      this.platformKits = options.platform_kits || {};
    });
  }

  list(): Subject<boolean> {
    const res$ = super.list();
    res$.subscribe(() => {
      this.dataService.changeCounter(this.data.length, "technicals");
    });
    return res$;
  }

  protected form_customizer(form, type) {
    // enrichment_kit is not part of the schema for genome studies (issue #61)
    const kitField = form.fields.find((f) => f.key === "enrichment_kit");
    if (!kitField) {
      return form;
    }

    const allKitOptions = kitField.templateOptions.options || [];

    kitField.expressionProperties = {
      ...(kitField.expressionProperties || {}),
      // filter the kit dropdown to only the kits compatible with the
      // currently selected platform (issue #62)
      "templateOptions.options": (model: any) => {
        if (!model || !model.platform) {
          return allKitOptions;
        }
        const compatibleKits = this.platformKits[model.platform];
        if (!compatibleKits) {
          return allKitOptions;
        }
        return allKitOptions.filter(
          (opt) => opt.value === "" || compatibleKits.includes(opt.value)
        );
      },
      // disable the kit dropdown until a platform is selected
      "templateOptions.disabled": (model: any) => !model || !model.platform,
      // clear a previously selected kit that is no longer compatible with the
      // (newly changed) platform
      "model.enrichment_kit": (model: any) => {
        if (!model || !model.platform || !model.enrichment_kit) {
          return model ? model.enrichment_kit : undefined;
        }
        const compatibleKits = this.platformKits[model.platform];
        if (compatibleKits && !compatibleKits.includes(model.enrichment_kit)) {
          return "";
        }
        return model.enrichment_kit;
      },
    };

    return form;
  }
}
