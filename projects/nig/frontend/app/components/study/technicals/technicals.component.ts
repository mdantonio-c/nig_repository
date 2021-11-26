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

  constructor(protected injector: Injector, private dataService: DataService) {
    super(injector);
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
  }

  list(): Subject<boolean> {
    const res$ = super.list();
    res$.subscribe(() => {
      this.dataService.changeCounter(this.data.length, "technicals");
    });
    return res$;
  }
}
